import pytest

from text2sql.etl.augment import (
    augment_mix,
    augment_record,
    build_pool,
    selected_for_augmentation,
)
from text2sql.etl.config import AugmentCfg
from text2sql.etl.mappers import map_gretel
from text2sql.etl.tokens import CharCounter, fill_token_counts
from text2sql.etl.validate import validate_record
from text2sql.schema import load_context
from text2sql.sqlexec import run_select

from . import fixtures as fx

CFG = AugmentCfg(rate=1.0, min_distractors=3, max_distractors=5, pool_records=50)


def train_rec(i):
    raw = fx.row(
        id=i,
        domain=f"d{i}",
        ctx=fx.PEOPLE_CTX.replace("people", f"people_{i}"),
        sql=f"SELECT COUNT(*) FROM people_{i} WHERE age > 26;",
    )
    rec = validate_record(map_gretel(f"gretel:train:{i}", raw))
    rec.split = "train"
    fill_token_counts([rec], CharCounter())
    return rec


def test_augmentation_is_label_preserving_and_adds_tables():
    recs = [train_rec(i) for i in range(12)]
    pool = build_pool(recs, CFG, seed=1)
    aug = augment_record(recs[0], pool, CFG, CharCounter(), 1800, seed=1)
    assert aug is not None and aug.augmented and aug.id.endswith("-aug")
    assert aug.n_tables >= recs[0].n_tables + 3
    assert aug.sql == recs[0].sql and aug.question == recs[0].question
    conn = load_context(recs[0].context_sqlite)
    assert len(run_select(conn, aug.sql).rows) == recs[0].result_rows


def test_pool_refuses_non_train_records():
    rec = train_rec(1)
    rec.split = "test_heldout"
    with pytest.raises(AssertionError):
        build_pool([rec], CFG, seed=1)


def test_token_budget_falls_back_to_plain_row():
    recs = [train_rec(i) for i in range(12)]
    pool = build_pool(recs, CFG, seed=1)
    out, stats = augment_mix(recs[:3], pool, CFG, CharCounter(), token_budget=5, seed=1)
    assert [r.augmented for r in out] == [False] * 3 and stats["AUG_FAILED"] == 3


def test_selection_is_stable_and_roughly_at_rate():
    recs = [train_rec(i) for i in range(40)]
    first = [selected_for_augmentation(r, 0.35, 42) for r in recs]
    assert first == [selected_for_augmentation(r, 0.35, 42) for r in reversed(recs)][::-1]
    assert 5 < sum(first) < 25
