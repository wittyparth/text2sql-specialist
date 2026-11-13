"""Stage 08: distractor-table augmentation for training rows.

Training schemas have 1-3 tables; a real database (Chinook) has 11. Adding unrelated tables from
other training records teaches the model to pick the right tables out of a crowded schema. The
change is label-preserving: the reference SQL is re-run on the enlarged database and has to
return the same number of rows.
"""

import hashlib
import random
import sqlite3
from collections import Counter
from dataclasses import dataclass, replace

from ..schema import canonicalize, load_context
from ..sqlexec import run_select
from .config import AugmentCfg
from .records import Record
from .tokens import TokenCounter, record_text


@dataclass
class TableCard:
    name: str
    columns: list[tuple[str, str, bool]]  # name, declared type, single-column primary key
    rows: list[tuple]


def _cards_from_context(ctx: str) -> list[TableCard]:
    try:
        conn = load_context(ctx)
    except sqlite3.Error:
        return []
    cards = []
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    )
    for (name,) in tables.fetchall():
        info = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
        n_pk = sum(1 for c in info if c[5])
        cols = [(c[1], c[2] or "TEXT", bool(c[5]) and n_pk == 1) for c in info]
        rows = conn.execute(f'SELECT * FROM "{name}" LIMIT 2').fetchall()
        cards.append(TableCard(name, cols, rows))
    conn.close()
    return cards


def build_pool(train_records: list[Record], cfg: AugmentCfg, seed: int) -> list[TableCard]:
    if any(r.split != "train" for r in train_records):
        raise AssertionError("distractor pool must come from train-domain records only")
    ordered = sorted(train_records, key=lambda r: r.id)
    picked = random.Random(seed).sample(ordered, min(cfg.pool_records, len(ordered)))
    pool: list[TableCard] = []
    for rec in picked:
        pool.extend(_cards_from_context(rec.context_sqlite))
    return pool


def _add_table(conn: sqlite3.Connection, card: TableCard) -> None:
    cols = ", ".join(f'"{n}" {t}{" PRIMARY KEY" if pk else ""}' for n, t, pk in card.columns)
    conn.execute(f'CREATE TABLE "{card.name}" ({cols})')
    if card.rows:
        marks = ", ".join("?" * len(card.columns))
        conn.executemany(f'INSERT INTO "{card.name}" VALUES ({marks})', card.rows)


def selected_for_augmentation(rec: Record, rate: float, seed: int) -> bool:
    """Stable per-record coin flip, so the choice doesn't depend on row order or batch size."""
    h = hashlib.sha256(f"{seed}:{rec.id}".encode()).digest()
    return int.from_bytes(h[:4], "big") / 2**32 < rate


def _pick_distractors(rec: Record, pool: list[TableCard], cfg: AugmentCfg, seed: int):
    rng = random.Random(f"{seed}:{rec.id}")
    k = rng.randint(cfg.min_distractors, cfg.max_distractors)
    own = {t.lower() for t in _own_tables(rec)}
    chosen: list[TableCard] = []
    for card in rng.sample(pool, min(len(pool), k * 4)):
        if card.name.lower() in own or any(card.name.lower() == c.name.lower() for c in chosen):
            continue
        chosen.append(card)
        if len(chosen) == k:
            break
    return chosen


def _own_tables(rec: Record) -> list[str]:
    conn = load_context(rec.context_sqlite)
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    conn.close()
    return names


def augment_record(
    rec: Record,
    pool: list[TableCard],
    cfg: AugmentCfg,
    counter: TokenCounter,
    token_budget: int,
    seed: int,
) -> Record | None:
    distractors = _pick_distractors(rec, pool, cfg, seed)
    for k in range(len(distractors), cfg.min_distractors - 1, -1):
        conn = load_context(rec.context_sqlite)
        for card in distractors[:k]:
            _add_table(conn, card)
        res = run_select(conn, rec.sql, timeout_s=2.0, max_rows=1000)
        if not res.ok or len(res.rows) != rec.result_rows:
            conn.close()
            return None
        candidate = replace(rec, id=rec.id + "-aug", augmented=True)
        candidate.schema_canonical = canonicalize(conn)
        candidate.n_tables = candidate.schema_canonical.count("CREATE TABLE")
        conn.close()
        candidate.n_tokens = counter.count_many([record_text(candidate)])[0]
        if candidate.n_tokens <= token_budget:
            return candidate
    return None


def augment_mix(
    mix: list[Record],
    pool: list[TableCard],
    cfg: AugmentCfg,
    counter: TokenCounter,
    token_budget: int,
    seed: int,
) -> tuple[list[Record], Counter]:
    stats: Counter = Counter()
    out = []
    for rec in mix:
        if not selected_for_augmentation(rec, cfg.rate, seed):
            out.append(rec)
            continue
        stats["attempted"] += 1
        aug = augment_record(rec, pool, cfg, counter, token_budget, seed)
        if aug is None:
            # keep the plain row rather than lose it; the failure is counted and reported
            stats["AUG_FAILED"] += 1
            out.append(rec)
        else:
            stats["augmented"] += 1
            out.append(aug)
    return out, stats
