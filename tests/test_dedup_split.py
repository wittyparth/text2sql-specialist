import pytest

from text2sql.etl.config import Config
from text2sql.etl.dedup import dedup, leakage_guard
from text2sql.etl.mappers import map_gretel, map_sqlcc
from text2sql.etl.records import Record
from text2sql.etl.split import (
    SplitError,
    allocate_stratified,
    allocate_weighted,
    assert_disjoint,
    assign_splits,
    split_domains,
)
from text2sql.etl.validate import validate_record

from . import fixtures as fx


def rec(raw, key=None):
    return validate_record(map_gretel(key or f"gretel:train:{raw['id']}", raw))


def test_exact_duplicate_and_conflicting_label():
    a = rec(fx.GOOD)
    b = rec(fx.GOOD, key="gretel:zz:1")  # sorts after a, so a is the survivor
    c = rec(fx.row(id=2, sql="SELECT COUNT(*) FROM people WHERE age >= 26;"))
    d = rec(
        fx.row(
            id=3, sql="SELECT name FROM people WHERE age > 100;", prompt="Another question here?"
        )
    )
    out = dedup([a, b, c, d])
    assert b.drop_reason == "DUP_EXACT" and a.status == "kept"
    assert out["DUP_CONFLICTING_LABEL"] == 1 and d.status == "kept"
    assert sum(r.status == "kept" for r in (a, c)) == 1  # same question + schema, different SQL


def test_cross_source_duplicate_prefers_gretel():
    g = rec(fx.row(id=5, prompt="Which sqlcc items have value above 3?"))
    s = validate_record(
        map_sqlcc(
            "sqlcc:3",
            {
                "question": "Which sqlcc items have value above 3?",
                "context": "CREATE TABLE t (name VARCHAR, value INT)",
                "answer": "SELECT name FROM t WHERE value > 3",
            },
        )
    )
    dedup([g, s])
    assert g.status == "kept" and s.drop_reason == "DUP_CROSS_SOURCE"


def test_split_is_seeded_and_disjoint():
    domains = [f"d{i}" for i in range(30)]
    a = split_domains(domains, 10, 5, seed=42)
    assert a == split_domains(domains, 10, 5, seed=42)
    assert len(a["test_heldout"]) == 10 and len(a["val"]) == 5 and len(a["train"]) == 15
    assert a["test_heldout"] != split_domains(domains, 10, 5, seed=7)["test_heldout"]
    assert_disjoint(a)


def test_overlap_is_caught():
    with pytest.raises(SplitError):
        assert_disjoint({"train": ["a", "b"], "val": ["c"], "test_heldout": ["b"]})


def test_too_few_domains_fails_loudly():
    cfg = Config(sources={}, sample={"class_weights": {}})
    records = [rec(fx.row(id=i, domain=f"d{i}")) for i in range(5)]
    with pytest.raises(SplitError):
        assign_splits(records, cfg)


def test_leakage_guard_removes_from_train_never_from_test():
    test = Record(
        id="t", status="kept", split="test_heldout", question="How many people?", sql="select 1"
    )
    twin = Record(id="a", status="kept", split="train", question="how many people", sql="select 2")
    sql_twin = Record(id="b", status="kept", split="val", question="other", sql="SELECT  1")
    clean = Record(id="c", status="kept", split="train", question="unrelated", sql="select 3")
    assert leakage_guard([test, twin, sql_twin, clean]) == 2
    assert test.status == "kept" and clean.status == "kept"
    assert twin.drop_reason == sql_twin.drop_reason == "LEAKAGE_OVERLAP"


def test_weighted_allocation_redistributes_shortfall_and_caps_basic():
    avail = {"basic": 1000, "aggregation": 1000, "window": 10}
    alloc = allocate_weighted(
        {"basic": 0.5, "aggregation": 0.3, "window": 0.2}, avail, 100, caps={"basic": 30}
    )
    assert alloc["window"] == 10 and alloc["basic"] <= 30
    assert sum(alloc.values()) == 100


def test_stratified_allocation_has_floor_and_hits_total():
    alloc = allocate_stratified({"basic": 900, "window": 40, "set_op": 10}, total=100, floor=25)
    assert alloc["window"] >= 25 and alloc["set_op"] == 10
    assert sum(alloc.values()) == 100
