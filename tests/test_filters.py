from text2sql.etl.config import FiltersCfg
from text2sql.etl.filters import apply_filters
from text2sql.etl.mappers import map_gretel
from text2sql.etl.validate import validate_record

from . import fixtures as fx

CFG = FiltersCfg(token_budget=1800)


def prep(raw, tokens=100):
    rec = validate_record(map_gretel(f"gretel:train:{raw['id']}", raw))
    rec.n_tokens = tokens
    return rec


def test_each_rule_has_a_reason():
    short = prep(fx.row(id=30, prompt="Hi?"))
    long_sql = prep(
        fx.row(id=31, sql="SELECT name FROM people WHERE " + " AND ".join(["age > 1"] * 400))
    )
    big = prep(fx.GOOD, tokens=2500)
    hardcoded = prep(fx.RELATIVE_HARDCODED)
    apply_filters([short, long_sql, big, hardcoded], CFG)
    assert short.drop_reason == "QUESTION_LENGTH"
    assert long_sql.drop_reason == "SQL_LENGTH"
    assert big.drop_reason == "TOKEN_BUDGET"
    assert hardcoded.drop_reason == "TIME_RELATIVE_HARDCODED"


def test_now_function_rows_are_kept_but_flagged():
    rec = prep(fx.RELATIVE_NOW)
    apply_filters([rec], CFG)
    assert rec.status == "kept" and rec.time_dependent


def test_empty_result_rows_are_kept_for_training():
    rec = prep(fx.EMPTY_RESULT)
    apply_filters([rec], CFG)
    assert rec.status == "kept" and rec.result_empty


def test_already_dropped_rows_keep_their_original_reason():
    rec = prep(fx.MISSING_COLUMN)
    apply_filters([rec], CFG)
    assert rec.drop_reason == "SQL_NO_SUCH_COLUMN"
