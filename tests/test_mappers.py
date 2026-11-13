from text2sql.etl.mappers import map_gretel, map_sqlcc, normalize_context, normalize_sql

from . import fixtures as fx


def test_gretel_mapping_and_key():
    rec = map_gretel("gretel:train:1", fx.GOOD)
    assert rec.source == "gretel" and rec.domain == "d0" and rec.source_id == "1"
    assert rec.sql_raw == "SELECT COUNT(*) FROM people WHERE age > 26"
    assert rec.context_raw.endswith(";")


def test_sqlcc_mapping_uses_pseudo_domain():
    rec = map_sqlcc(
        "sqlcc:3",
        {"question": "How many ?", "context": "CREATE TABLE t (a INT)", "answer": "SELECT 1"},
    )
    assert rec.domain == "sqlcc" and rec.source_id is None
    assert rec.question == "How many?" and rec.context_raw == "CREATE TABLE t (a INT);"


def test_empty_fields_are_dropped_not_crashed():
    rec = map_gretel("gretel:train:9", {**fx.GOOD, "sql_prompt": "   "})
    assert rec.drop_reason == "EMPTY_FIELD"


def test_sql_normalization_leaves_string_literals_alone():
    assert normalize_sql("SELECT  'a   b' ,\n  x  FROM t ;") == "SELECT 'a   b' , x FROM t"
    assert normalize_context("CREATE TABLE t (a INT)") == "CREATE TABLE t (a INT);"
