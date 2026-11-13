from text2sql.schema import load_context
from text2sql.sqlexec import (
    results_match,
    results_match_strict,
    run_select,
    safe_connect,
)


def test_select_returns_rows_and_columns():
    conn = load_context("CREATE TABLE t (a, b); INSERT INTO t VALUES (1, 'x'), (2, 'y');")
    res = run_select(conn, "SELECT a, b FROM t ORDER BY a")
    assert res.ok and res.rows == [(1, "x"), (2, "y")] and res.columns == ["a", "b"]


def test_writes_are_blocked_and_leave_data_alone():
    conn = load_context("CREATE TABLE t (a); INSERT INTO t VALUES (1);")
    blocked = ("DELETE FROM t", "DROP TABLE t", "INSERT INTO t VALUES (2)", "PRAGMA table_info(t)")
    for sql in blocked:
        res = run_select(conn, sql)
        assert not res.ok and res.error_class == "NOT_AUTHORIZED", sql
    assert run_select(conn, "SELECT count(*) FROM t").rows == [(1,)]


def test_read_only_file_connection(chinook_path):
    res = run_select(safe_connect(chinook_path), "SELECT count(*) FROM Artist")
    assert res.rows == [(275,)]


def test_runaway_query_times_out():
    conn = load_context("")
    sql = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT max(n) FROM r"
    res = run_select(conn, sql, timeout_s=0.3)
    assert not res.ok and res.error_class == "TIMEOUT" and res.elapsed_s < 2


def test_truncation_flag():
    conn = load_context("CREATE TABLE t (a);" + "INSERT INTO t VALUES (1);" * 20)
    res = run_select(conn, "SELECT * FROM t", max_rows=5)
    assert res.ok and len(res.rows) == 5 and res.truncated


def test_error_classes():
    conn = load_context("CREATE TABLE t (a);")
    assert run_select(conn, "SELECT zz FROM t").error_class == "SQL_NO_SUCH_COLUMN"
    assert run_select(conn, "SELECT a FROM nope").error_class == "SQL_NO_SUCH_TABLE"
    assert run_select(conn, "SELECT YEAR(a) FROM t").error_class == "SQL_NO_SUCH_FUNCTION"
    assert run_select(conn, "SELEC a FROM t").error_class == "SQL_SYNTAX"


def test_column_order_does_not_matter():
    assert results_match([(1, "a")], [("a", 1)])


def test_numeric_strings_and_floats():
    assert results_match([("2009",)], [(2009,)])
    assert results_match([(94,)], [(94.0,)])
    assert results_match([(3.14159,)], [(3.14,)])
    assert not results_match([(94,)], [(95,)])


def test_midnight_datetime_matches_date():
    assert results_match([("2009-01-01 00:00:00",)], [("2009-01-01",)])
    assert not results_match([("2009-01-01 10:00:00",)], [("2009-01-01",)])


def test_row_order_only_matters_when_asked():
    a, b = [(1,), (2,)], [(2,), (1,)]
    assert results_match(a, b, ordered=False)
    assert not results_match(a, b, ordered=True)


def test_extra_column_or_row_is_wrong():
    assert not results_match([(1, 2)], [(1,)])
    assert not results_match([(1,), (1,)], [(1,)])


def test_nulls_and_case():
    assert results_match([(None,)], [(None,)])
    assert not results_match([("Rock",)], [("rock",)])


def test_strict_is_stricter():
    assert not results_match_strict([(1, "a")], [("a", 1)])
    assert not results_match_strict([("2009",)], [(2009,)])
