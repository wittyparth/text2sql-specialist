import time

import pytest

from text2sql.etl.mappers import map_gretel
from text2sql.etl.validate import derive_complexity, parse_statements, scope_error, validate_record

from . import fixtures as fx


def validated(raw: dict):
    return validate_record(map_gretel(f"gretel:train:{raw['id']}", raw))


@pytest.mark.parametrize(
    "raw, reason",
    [
        (fx.GOOD, None),
        (fx.MYSQL_YEAR, None),
        (fx.CREATE_SCHEMA_CTX, None),
        (fx.PUBLIC_QUALIFIED, None),
        (fx.NO_DATA_CTX, None),
        (fx.EMPTY_RESULT, None),
        (fx.AMBIGUOUS_5097, "SQL_AMBIGUOUS"),
        (fx.MISSING_COLUMN, "SQL_NO_SUCH_COLUMN"),
        (fx.MISSING_TABLE, "SQL_NO_SUCH_TABLE"),
        (fx.WITH_DELETE, "NOT_SELECT"),
        (fx.UPDATE_ROW, "NOT_SELECT"),
        (fx.MULTI_STATEMENT, "MULTI_STATEMENT"),
        (fx.BROKEN_CONTEXT, "CTX_LOAD_FAILED"),
        (fx.DUPLICATE_KEY_CONTEXT, "CTX_LOAD_FAILED"),
    ],
)
def test_fixture_outcomes(raw, reason):
    rec = validated(raw)
    assert rec.drop_reason == reason
    assert rec.status == ("dropped" if reason else "kept")


def test_headline_row_5097_is_ambiguous():
    rec = validated(fx.AMBIGUOUS_5097)
    assert rec.drop_reason == "SQL_AMBIGUOUS"
    assert "ambiguous column name" in rec.drop_detail


def test_mysql_year_is_repaired_and_runs():
    rec = validated(fx.MYSQL_YEAR)
    assert rec.repaired and rec.repair_dialect == "mysql"
    assert "year(" not in rec.sql.lower()
    assert rec.result_rows == 1


def test_schema_and_public_qualifier_cleanup():
    assert validated(fx.CREATE_SCHEMA_CTX).status == "kept"
    rec = validated(fx.PUBLIC_QUALIFIED)
    assert rec.status == "kept" and "public." not in rec.context_sqlite


def test_validation_level_and_emptiness():
    assert validated(fx.GOOD).validation_level == "result"
    no_data = validated(fx.NO_DATA_CTX)
    assert no_data.validation_level == "schema" and not no_data.result_empty
    empty = validated(fx.EMPTY_RESULT)
    assert empty.validation_level == "result" and empty.result_empty


def test_runaway_cte_times_out_quickly():
    started = time.monotonic()
    rec = validate_record(map_gretel("gretel:train:16", fx.RUNAWAY), timeout_s=0.5)
    assert rec.drop_reason == "TIMEOUT"
    assert time.monotonic() - started < 3


def test_canonical_schema_and_id_are_set():
    rec = validated(fx.GOOD)
    assert rec.schema_canonical.startswith("CREATE TABLE people (id INT, name VARCHAR(20)")
    assert rec.n_tables == 1 and len(rec.id) == 16
    assert rec.id == validated(fx.GOOD).id


def test_order_matters_and_complexity():
    ordered = fx.row(id=20, sql="SELECT name FROM people ORDER BY age DESC;")
    assert validated(ordered).order_matters
    assert not validated(fx.GOOD).order_matters
    cases = {
        "SELECT 1": "basic",
        "SELECT count(*) FROM t": "aggregation",
        "SELECT * FROM a JOIN b ON a.i = b.i": "single_join",
        "SELECT * FROM a JOIN b ON a.i = b.i JOIN c ON c.i = b.i": "multi_join",
        "SELECT * FROM a WHERE x IN (SELECT x FROM b)": "subquery",
        "SELECT x, rank() OVER (ORDER BY y) FROM a": "window",
        "SELECT x FROM a UNION SELECT x FROM b": "set_op",
        "WITH c AS (SELECT 1) SELECT * FROM c": "cte",
    }
    for sql, expected in cases.items():
        assert derive_complexity(parse_statements(sql)[0]) == expected, sql


def test_scope_error_codes():
    assert scope_error("DELETE FROM t")[0] == "NOT_SELECT"
    assert scope_error("SELECT 1; SELECT 2")[0] == "MULTI_STATEMENT"
    assert scope_error("SELECT 1 UNION SELECT 2")[0] is None


def test_week_intervals_become_days_so_they_do_not_evaluate_to_null():
    raw = fx.row(
        id=40,
        prompt="Who joined in the last week?",
        ctx="CREATE TABLE j (n TEXT, d DATE); INSERT INTO j VALUES ('a', date('now', '-2 days'));",
        sql="SELECT n FROM j WHERE d >= DATE_SUB(CURDATE(), INTERVAL 1 WEEK);",
    )
    rec = validated(raw)
    assert rec.status == "kept" and rec.repaired
    assert "'-7 days'" in rec.sql and rec.result_rows == 1


def test_year_month_day_are_rewritten_to_strftime():
    raw = fx.row(
        id=41,
        sql="SELECT MONTH(d), DAY(d) FROM j;",
        ctx="CREATE TABLE j (d DATE); INSERT INTO j VALUES ('2023-05-17');",
    )
    rec = validated(raw)
    assert rec.status == "kept" and "strftime" in rec.sql.lower() and rec.result_rows == 1
