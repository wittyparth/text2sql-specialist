"""Write the demo databases and example questions the app ships with.

Chinook is already in data/demo. This adds three small databases taken from the held-out test
domains (never seen in training) and writes data/demo/examples.json.

    uv run python scripts/build_demo_dbs.py
"""

import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from text2sql.etl.load import read_records
from text2sql.schema import load_context

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data" / "demo"
N_DOMAINS = 3
CHINOOK_EXAMPLES = 8


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def pick_heldout_schemas(records) -> list[list]:
    """Held-out schemas shared by several questions; prefer more tables, one per domain."""
    pool = [
        r
        for r in records
        if r.split == "test_heldout"
        and r.status == "kept"
        and r.validation_level == "result"
        and not r.result_empty
        and not r.time_dependent
    ]
    by_schema = defaultdict(list)
    for r in pool:
        by_schema[r.schema_canonical].append(r)
    ranked = sorted(
        (v for v in by_schema.values() if len(v) >= 3),
        key=lambda v: (-v[0].n_tables, -len(v), v[0].domain),
    )
    chosen, seen = [], set()
    for group in ranked:
        if group[0].domain not in seen:
            seen.add(group[0].domain)
            chosen.append(sorted(group, key=lambda r: r.id)[:6])
        if len(chosen) == N_DOMAINS:
            break
    return chosen


def write_db(path: Path, context_sql: str) -> None:
    path.unlink(missing_ok=True)
    src, dst = load_context(context_sql), sqlite3.connect(path)
    src.backup(dst)
    dst.close()
    src.close()


def chinook_examples() -> list[dict]:
    """Mix of difficulties, leading with questions the base model got wrong in the latest run."""
    items = [
        json.loads(x) for x in (ROOT / "data/eval/chinook_eval.jsonl").read_text().splitlines()
    ]
    wrong: list[str] = []
    runs = sorted((ROOT / "runs").glob("*_base-q4_chinook"))
    if runs:
        rows = [json.loads(x) for x in (runs[-1] / "predictions.jsonl").read_text().splitlines()]
        wrong = [r["id"] for r in rows if not r["ok"]]
    by_id = {i["id"]: i for i in items}
    picked: list[dict] = []
    seen_diff: dict[str, int] = defaultdict(int)
    for item_id in wrong:  # at most 2 per difficulty so the list stays varied
        item = by_id[item_id]
        if seen_diff[item["difficulty"]] < 2 and len(picked) < 4:
            picked.append(item)
            seen_diff[item["difficulty"]] += 1
    for item in items:
        if len(picked) >= CHINOOK_EXAMPLES:
            break
        if item not in picked and seen_diff[item["difficulty"]] < 2:
            picked.append(item)
            seen_diff[item["difficulty"]] += 1
    return [
        {
            "question": i["question"],
            "sql": i["sql"],
            "order_matters": i["order_matters"],
            "difficulty": i["difficulty"],
            "base_got_wrong": i["id"] in wrong,
        }
        for i in picked
    ]


def main() -> None:
    records = read_records(ROOT / "data/processed/records.parquet")
    presets = [
        {
            "key": "chinook",
            "label": "Chinook: music store, 11 tables",
            "file": "chinook.sqlite",
            "unseen": False,
            "examples": chinook_examples(),
        }
    ]
    for group in pick_heldout_schemas(records):
        first = group[0]
        name = f"heldout_{slug(first.domain)}"
        write_db(DEMO / f"{name}.sqlite", first.context_sqlite)
        presets.append(
            {
                "key": name,
                "label": f"Unseen domain: {first.domain}",
                "file": f"{name}.sqlite",
                "unseen": True,
                "examples": [
                    {
                        "question": r.question,
                        "sql": r.sql,
                        "order_matters": r.order_matters,
                        "difficulty": r.complexity_derived,
                    }
                    for r in group
                ],
            }
        )
    (DEMO / "examples.json").write_text(json.dumps({"presets": presets}, indent=2))
    for p in presets:
        print(p["key"], len(p["examples"]), "examples")


if __name__ == "__main__":
    main()
