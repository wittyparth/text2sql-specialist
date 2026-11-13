"""ETL entry point: `python -m text2sql.etl.pipeline run | status`."""

import argparse
import json
import logging
import os
import secrets
import sys
import time
from collections import Counter
from pathlib import Path

from .augment import augment_mix, build_pool
from .config import Config
from .dedup import dedup, leakage_guard
from .extract import ensure_source, iter_gretel, iter_sqlcc
from .filters import apply_filters
from .load import (
    PipelineError,
    dumps_jsonl,
    eval_row,
    push_dataset,
    read_records,
    recheck_rows,
    render_card,
    train_row,
    write_frozen,
    write_records,
)
from .manifest import Manifest, atomic_write
from .mappers import MAPPERS
from .records import Record
from .report import build_report, write_report
from .split import assign_splits, pick_eval_set, pick_train_mix, pick_val_set
from .tokens import TokenCounter, fill_token_counts
from .validate import validate_all

log = logging.getLogger("etl")
READERS = {"gretel": iter_gretel, "sqlcc": iter_sqlcc}


class Stages:
    """Per-stage in/out counts and wall time, rendered into the report."""

    def __init__(self) -> None:
        self.items: list[dict] = []
        self._t = time.monotonic()

    def done(self, name: str, n_in: int, n_out: int) -> None:
        now = time.monotonic()
        self.items.append(
            {"name": name, "n_in": n_in, "n_out": n_out, "seconds": round(now - self._t, 1)}
        )
        self._t = now


def n_kept(records: list[Record]) -> int:
    return sum(r.status == "kept" for r in records)


def default_counter(cfg: Config) -> TokenCounter:
    from .tokens import QwenCounter

    return QwenCounter(cfg.filters.tokenizer)


def ingest(
    cfg: Config, manifest: Manifest, limit: int | None, counter: TokenCounter, run_id: str
) -> tuple[list[Record], dict]:
    """extract -> map -> validate -> canonicalize, only for rows we haven't processed before."""
    interim = cfg.paths.interim / "validated.parquet"
    existing = read_records(interim) if interim.exists() else []
    done = {r.source_row_key for r in existing}
    new: list[Record] = []
    downloaded = 0
    for name, reader in READERS.items():
        paths, n = ensure_source(name, cfg, manifest)
        downloaded += n
        new += [MAPPERS[name](key, row) for key, row in reader(paths, done, limit)]
    if "chinook" in cfg.sources:
        downloaded += ensure_source("chinook", cfg, manifest)[1]
    log.info("extract: %d files downloaded", downloaded)
    keys = [r.source_row_key for r in new]
    if len(keys) != len(set(keys)):
        raise PipelineError("source_row_key is not unique")
    for rec in new:
        rec.run_id = run_id
    v = cfg.validate_
    new = validate_all(new, v.timeout_s, v.max_rows, v.workers)
    fill_token_counts(new, counter)
    records = existing + new
    write_records(interim, records)
    return records, {"new": len(new), "skipped": len(existing)}


def build(cfg: Config, records: list[Record], counter: TokenCounter, stages: Stages) -> dict:
    """filters -> dedup -> split -> leakage -> sample -> augment. Pure recompute from `records`."""
    before = n_kept(records)
    apply_filters(records, cfg.filters)
    stages.done("filters", before, n_kept(records))
    before = n_kept(records)
    dedup(records)
    stages.done("dedup", before, n_kept(records))
    before = n_kept(records)
    domains = assign_splits(records, cfg)
    leaked = leakage_guard(records)
    stages.done("split + leakage guard", before, n_kept(records))

    mix = pick_train_mix(records, cfg)
    val_set, eval_set = pick_val_set(records, cfg), pick_eval_set(records, cfg)
    train_records = [r for r in records if r.split == "train" and r.status == "kept"]
    pool = build_pool(train_records, cfg.augment, cfg.seed)
    mix_aug, aug_stats = augment_mix(
        mix, pool, cfg.augment, counter, cfg.filters.token_budget, cfg.seed
    )
    stages.done("sample + augment", len(mix), len(mix_aug))

    # an augmented row replaces its original so nothing is counted twice
    replaced = {r.id.removesuffix("-aug") for r in mix_aug if r.augmented}
    final = [r for r in records if r.id not in replaced] + [r for r in mix_aug if r.augmented]
    for r in mix_aug + val_set + eval_set:
        r.sampled = True
    return {
        "records": final,
        "mix": mix_aug,
        "val": val_set,
        "eval": eval_set,
        "domains": domains,
        "leaked": leaked,
        "aug_stats": dict(aug_stats),
    }


def write_outputs(cfg: Config, built: dict, *, partial: bool, refreeze: bool) -> dict:
    proc = cfg.paths.processed
    write_records(proc / "records.parquet", built["records"])
    atomic_write(proc / "train.jsonl", dumps_jsonl([train_row(r) for r in built["mix"]]))
    atomic_write(proc / "val.jsonl", dumps_jsonl([train_row(r) for r in built["val"]]))
    status = "skipped (partial run)"
    if not partial:
        text = dumps_jsonl([eval_row(r) for r in built["eval"]])
        status = write_frozen(cfg.paths.eval / "gretel_heldout_eval.jsonl", text, refreeze)
    return {"eval_file": status, "rechecked": recheck_rows(built["mix"], 200, cfg.seed)}


def counts_by_class(recs: list[Record]) -> dict:
    return {"n": len(recs), "by_class": dict(Counter(r.complexity_derived for r in recs))}


def chinook_prompt_tokens(cfg: Config, counter: TokenCounter) -> int | None:
    path = cfg.paths.eval / "chinook_eval.jsonl"
    db = Path("data/demo/chinook.sqlite")
    if not (path.exists() and db.exists()):
        return None
    from ..prompt import build_messages
    from ..schema import canonicalize
    from ..sqlexec import safe_connect
    from .tokens import render_chatml

    question = json.loads(path.read_text().splitlines()[0])["question"]
    text = render_chatml(build_messages(canonicalize(safe_connect(db)), question))
    return counter.count_many([text])[0]


def make_report(cfg, built, manifest, inc, stages, counter, run_id) -> dict:
    eval_counts = {
        "gretel_heldout": counts_by_class(built["eval"]),
        "gretel_val": counts_by_class(built["val"]),
    }
    chinook = cfg.paths.eval / "chinook_eval.jsonl"
    if chinook.exists():
        rows = [json.loads(line) for line in chinook.read_text().splitlines() if line]
        eval_counts["chinook"] = {
            "n": len(rows),
            "by_class": dict(Counter(r["difficulty"] for r in rows)),
        }
    split_counts = Counter(r.split for r in built["records"] if r.sampled)
    return build_report(
        built["records"],
        run_id=run_id,
        config=cfg.model_dump(mode="json"),
        manifest=manifest.data,
        split_info={"domains": built["domains"], "leakage_removed": built["leaked"]},
        stage_stats=stages.items,
        incremental=inc,
        eval_counts=eval_counts,
        aug_stats=built["aug_stats"],
        mix_counts={
            "train": len(built["mix"]),
            "val": split_counts["val"],
            "test_heldout": split_counts["test_heldout"],
        },
        chinook_tokens=chinook_prompt_tokens(cfg, counter),
    )


def publish(cfg: Config, rep: dict) -> None:
    user, token = os.environ.get("HF_USER"), os.environ.get("HF_TOKEN")
    if not (user and token):
        raise PipelineError("--push needs HF_USER and HF_TOKEN in the environment")
    repo = f"{user}/text2sql-sqlite-clean"
    eval_path = cfg.paths.eval / "gretel_heldout_eval.jsonl"
    url = push_dataset(cfg.paths.processed, eval_path, render_card(rep, repo), repo, token)
    log.info("pushed: %s", url)


def run(
    cfg: Config,
    *,
    limit: int | None = None,
    only_stage: str | None = None,
    push: bool = False,
    refreeze: bool = False,
    counter: TokenCounter | None = None,
) -> dict:
    if push and limit:
        raise PipelineError("refusing to push a partial (--limit) dataset")
    counter = counter or default_counter(cfg)
    manifest = Manifest(cfg.paths.state / "manifest.json")
    run_id = secrets.token_hex(4)
    stages = Stages()
    t0 = time.monotonic()
    records, inc = ingest(cfg, manifest, limit, counter, run_id)
    manifest.save()
    stages.done("ingest (map + validate + canonicalize)", inc["new"], n_kept(records))
    log.info("ingest: new=%d skipped=%d", inc["new"], inc["skipped"])
    summary = {"run_id": run_id, **inc, "limit": limit}
    if only_stage != "ingest":
        built = build(cfg, records, counter, stages)
        info = write_outputs(cfg, built, partial=bool(limit), refreeze=refreeze)
        log.info("outputs: eval %s, %d rows rechecked", info["eval_file"], info["rechecked"])
        rep = make_report(cfg, built, manifest, inc, stages, counter, run_id)
        write_report(rep, cfg.paths.reports)
        summary |= {"train_rows": len(built["mix"]), "eval_rows": len(built["eval"])}
        if push:
            publish(cfg, rep)
    summary["seconds"] = round(time.monotonic() - t0, 1)
    manifest.add_run(summary)
    manifest.save()
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m text2sql.etl.pipeline", description=__doc__)
    ap.add_argument("--config", default="configs/pipeline.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the pipeline")
    r.add_argument("--limit", type=int, help="cap rows per source (file order)")
    r.add_argument("--only-stage", choices=["ingest"], help="stop after extract/validate")
    r.add_argument("--push", action="store_true", help="publish the dataset to the HF Hub")
    r.add_argument("--refreeze-eval", action="store_true", help="overwrite the frozen eval file")
    sub.add_parser("status", help="print the manifest")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S"
    )
    for noisy in ("httpx", "httpx2", "huggingface_hub", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = Config.load(args.config)
    if args.cmd == "status":
        print(
            json.dumps(Manifest(cfg.paths.state / "manifest.json").data, indent=2, sort_keys=True)
        )
        return 0
    try:
        out = run(
            cfg,
            limit=args.limit,
            only_stage=args.only_stage,
            push=args.push,
            refreeze=args.refreeze_eval,
        )
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
