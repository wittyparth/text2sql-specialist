import hashlib
import json
from pathlib import Path

import pytest

from text2sql.etl.config import Config
from text2sql.etl.load import PipelineError, read_records
from text2sql.etl.pipeline import run
from text2sql.etl.tokens import CharCounter

from . import fixtures as fx


@pytest.fixture
def cfg(tmp_path) -> Config:
    g = tmp_path / "in" / "synthetic_text_to_sql_train.snappy.parquet"
    s = tmp_path / "in" / "sqlcc.json"
    g.parent.mkdir()
    fx.synthetic_gretel(g, n_domains=20, per_domain=8)
    fx.synthetic_sqlcc(s, 30)
    return Config(
        sources={
            "gretel": {"kind": "local", "files": [str(g)]},
            "sqlcc": {"kind": "local", "files": [str(s)]},
        },
        paths={
            k: tmp_path / "out" / k
            for k in ("raw", "interim", "processed", "state", "eval", "reports")
        },
        split={
            "test_domains": 4,
            "val_domains": 2,
            "eval_size": 12,
            "eval_floor_per_class": 2,
            "val_size": 6,
        },
        sample={
            "gretel": 60,
            "sqlcc": 10,
            "class_weights": {
                "basic": 0.25,
                "aggregation": 0.25,
                "single_join": 0.25,
                "subquery": 0.25,
            },
        },
        augment={"rate": 0.5, "pool_records": 30, "min_distractors": 2, "max_distractors": 4},
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def outputs(cfg) -> dict[str, str]:
    p = cfg.paths
    return {
        "train": digest(p.processed / "train.jsonl"),
        "val": digest(p.processed / "val.jsonl"),
        "eval": digest(p.eval / "gretel_heldout_eval.jsonl"),
        "records": json.dumps(
            [r.to_dict() for r in read_records(p.processed / "records.parquet")], sort_keys=True
        ),
    }


def test_second_run_is_a_noop_with_identical_outputs(cfg):
    first = run(cfg, counter=CharCounter())
    before = outputs(cfg)
    second = run(cfg, counter=CharCounter())
    assert first["new"] == 20 * 8 + 30 and second["new"] == 0 and second["skipped"] == first["new"]
    assert outputs(cfg) == before


def test_incremental_run_only_processes_the_remainder(cfg):
    partial = run(cfg, limit=50, counter=CharCounter())
    full = run(cfg, counter=CharCounter())
    assert partial["new"] == 80 and full["new"] == (20 * 8 + 30) - 80
    fresh_cfg = cfg.model_copy(deep=True)
    for k in ("interim", "processed", "state", "eval", "reports"):
        setattr(fresh_cfg.paths, k, getattr(cfg.paths, k).parent / (k + "_fresh"))
    run(fresh_cfg, counter=CharCounter())
    # same final data whether it arrived in one go or in two
    assert digest(cfg.paths.processed / "train.jsonl") == digest(
        fresh_cfg.paths.processed / "train.jsonl"
    )


def test_partial_run_does_not_touch_the_frozen_eval_file(cfg):
    run(cfg, limit=50, counter=CharCounter())
    assert not (cfg.paths.eval / "gretel_heldout_eval.jsonl").exists()


def test_frozen_eval_file_blocks_silent_changes(cfg):
    run(cfg, counter=CharCounter())
    path = cfg.paths.eval / "gretel_heldout_eval.jsonl"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(PipelineError, match="frozen"):
        run(cfg, counter=CharCounter())
    run(cfg, counter=CharCounter(), refreeze=True)


def test_invariants_on_the_outputs(cfg):
    run(cfg, counter=CharCounter())
    records = read_records(cfg.paths.processed / "records.parquet")
    keys = [r.source_row_key for r in records if not r.augmented]
    assert len(keys) == len(set(keys))
    domains = {
        s: {r.domain for r in records if r.split == s and r.source == "gretel"}
        for s in ("train", "val", "test_heldout")
    }
    assert not (domains["train"] & domains["test_heldout"])
    assert not (domains["train"] & domains["val"]) and not (
        domains["val"] & domains["test_heldout"]
    )
    train = [
        json.loads(line) for line in (cfg.paths.processed / "train.jsonl").read_text().splitlines()
    ]
    assert len(train) == 70
    assert any(t["meta"]["augmented"] for t in train)
    assert all(t["messages"][-1]["role"] == "assistant" for t in train)
    assert (cfg.paths.reports / "data_quality.md").exists()
