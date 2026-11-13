"""Stage 06: deduplication in three passes, plus the leakage guard that runs after the split."""

import hashlib
from collections import Counter, defaultdict

from .records import Record, norm_text

_SOURCE_PRIORITY = {"gretel": 0, "sqlcc": 1}


def _order(rec: Record) -> tuple:
    return (_SOURCE_PRIORITY.get(rec.source, 9), rec.source_row_key)


def _kept(records: list[Record]) -> list[Record]:
    return sorted((r for r in records if r.status == "kept"), key=_order)


def _schema_hash(rec: Record) -> str:
    return hashlib.sha256(rec.schema_canonical.encode()).hexdigest()


def dedup(records: list[Record]) -> Counter:
    dropped: Counter = Counter()

    seen: set[str] = set()
    for rec in _kept(records):
        if rec.id in seen:
            rec.drop("DUP_EXACT")
            dropped["DUP_EXACT"] += 1
        seen.add(rec.id)

    groups = defaultdict(list)
    for rec in _kept(records):
        groups[(norm_text(rec.question), _schema_hash(rec))].append(rec)
    for group in groups.values():
        if len(group) > 1:
            # same question on the same schema with different SQL: keep the most informative label
            best = min(group, key=lambda r: (r.result_empty, len(r.sql), _order(r)))
            for rec in group:
                if rec is not best:
                    rec.drop("DUP_CONFLICTING_LABEL")
                    dropped["DUP_CONFLICTING_LABEL"] += 1

    by_question = defaultdict(list)
    for rec in _kept(records):
        by_question[norm_text(rec.question)].append(rec)
    for group in by_question.values():
        if len({r.source for r in group}) > 1:
            for rec in group:
                if rec.source != "gretel":
                    rec.drop("DUP_CROSS_SOURCE")
                    dropped["DUP_CROSS_SOURCE"] += 1
    return dropped


def leakage_guard(records: list[Record]) -> int:
    """Remove train/val rows whose question or SQL also appears in the held-out test split."""
    test = [r for r in records if r.status == "kept" and r.split == "test_heldout"]
    questions = {norm_text(r.question) for r in test}
    sqls = {norm_text(r.sql) for r in test}
    removed = 0
    for rec in records:
        if rec.status == "kept" and rec.split in ("train", "val"):
            if norm_text(rec.question) in questions or norm_text(rec.sql) in sqls:
                rec.drop("LEAKAGE_OVERLAP")
                removed += 1
    return removed
