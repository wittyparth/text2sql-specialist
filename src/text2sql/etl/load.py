"""Stage 09: write the outputs (Parquet, chat JSONL, frozen eval file) and publish to the Hub."""

import json
import os
import random
import shutil
import types
from dataclasses import fields
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ..prompt import build_messages
from ..schema import load_context
from ..sqlexec import run_select
from .manifest import atomic_write
from .records import Record

_ARROW_TYPES = {str: pa.string(), int: pa.int64(), bool: pa.bool_()}


class PipelineError(RuntimeError):
    pass


def _arrow_type(tp) -> pa.DataType:
    if isinstance(tp, types.UnionType):
        tp = next(t for t in tp.__args__ if t is not type(None))
    return _ARROW_TYPES[tp]


def arrow_schema() -> pa.Schema:
    return pa.schema([(f.name, _arrow_type(f.type)) for f in fields(Record)])


def write_records(path: Path, records: list[Record]) -> None:
    rows = [r.to_dict() for r in sorted(records, key=lambda r: (r.id, r.source_row_key))]
    table = pa.Table.from_pylist(rows, schema=arrow_schema())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)


def read_records(path: Path) -> list[Record]:
    return [Record.from_dict(d) for d in pq.read_table(path).to_pylist()]


def dumps_jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def train_row(rec: Record) -> dict:
    return {
        "messages": build_messages(rec.schema_canonical, rec.question, rec.sql),
        "meta": {
            "id": rec.id,
            "source": rec.source,
            "domain": rec.domain,
            "complexity": rec.complexity_derived,
            "augmented": rec.augmented,
            "repaired": rec.repaired,
        },
    }


def val_row(rec: Record) -> dict:
    """Validation rows also carry what the notebook needs to execute predictions."""
    row = train_row(rec)
    row["meta"] |= {
        "context_sqlite": rec.context_sqlite,
        "gold_sql": rec.sql,
        "order_matters": rec.order_matters,
    }
    return row


def eval_row(rec: Record) -> dict:
    return {
        "id": rec.id,
        "domain": rec.domain,
        "difficulty": rec.complexity_derived,
        "question": rec.question,
        "schema_canonical": rec.schema_canonical,
        "context_sqlite": rec.context_sqlite,
        "sql": rec.sql,
        "order_matters": rec.order_matters,
        "expected_row_count": rec.result_rows,
    }


def write_frozen(path: Path, text: str, refreeze: bool) -> str:
    """Write the eval file once. Later runs only verify it, so scores stay comparable."""
    if path.exists() and not refreeze:
        if path.read_text() != text:
            raise PipelineError(
                f"{path} is frozen but the pipeline would now produce different content. "
                "Pass --refreeze-eval if the sources changed on purpose (old scores won't compare)."
            )
        return "verified"
    atomic_write(path, text)
    return "written"


def recheck_rows(recs: list[Record], n: int, seed: int) -> int:
    """Final guard: a random sample of shipped rows must still execute with the stored row count."""
    sample = random.Random(seed).sample(recs, min(n, len(recs)))
    for rec in sample:
        conn = load_context(rec.context_sqlite)
        res = run_select(conn, rec.sql, timeout_s=2.0)
        conn.close()
        if not res.ok or len(res.rows) != rec.result_rows:
            raise PipelineError(f"record {rec.id} no longer executes cleanly: {res.message}")
    return len(sample)


def render_card(report: dict, repo_id: str) -> str:
    f = report["funnel"]
    split = report["split"]
    rev_g = report["revisions"].get("gretel", "")[:12]
    rev_s = report["revisions"].get("sqlcc", "")[:12]
    leaked = split["leakage_removed"]
    aug_pct = report["augment"].get("share_pct", 0)
    rows = "\n".join(
        f"| {k} | {f['gretel'].get(k, '')} | {f['sqlcc'].get(k, '')} |" for k in f["gretel"]
    )
    return f"""---
license: apache-2.0
language: [en]
task_categories: [text-generation]
tags: [text-to-sql, sqlite, etl, execution-validated]
configs:
- config_name: train
  data_files: [{{split: train, path: train.jsonl}}]
- config_name: validation
  data_files: [{{split: validation, path: validation.jsonl}}]
- config_name: test_heldout
  data_files: [{{split: test, path: test_heldout.jsonl}}]
- config_name: all_records
  data_files: [{{split: train, path: all_records.parquet}}]
---

# {repo_id}

Execution-validated text-to-SQL data for SQLite, built by a reproducible ETL pipeline
(see the code repository for `make pipeline`). Every training example was run in SQLite;
examples that did not run were repaired with sqlglot where possible and dropped otherwise.
`all_records` keeps every source row with its `status` and `drop_reason`, so nothing is hidden.

## Sources and licenses
- [gretelai/synthetic_text_to_sql](https://huggingface.co/datasets/gretelai/synthetic_text_to_sql),
  Apache-2.0 (revision `{rev_g}`)
- [b-mc2/sql-create-context](https://huggingface.co/datasets/b-mc2/sql-create-context),
  CC-BY-4.0 (derived from WikiSQL and Spider; revision
  `{rev_s}`)
- Chinook sample database, used only for evaluation, not included here.

## Funnel
| Stage | Gretel | sql-create-context |
|---|---|---|
{rows}

## Splits
Gretel's own train/test files are pooled and re-split **by domain**, so evaluation measures
generalization to unseen schemas and topics.
- test_heldout domains: {", ".join(split["domains"]["test_heldout"])}
- validation domains: {", ".join(split["domains"]["val"])}
- {len(split["domains"]["train"])} training domains. Overlap between the lists: none (asserted).
- Leakage guard: {leaked} train/val rows removed for matching a test question or SQL.

## Format
`train.jsonl` / `validation.jsonl`: `messages` (system, user, assistant) and `meta`.
User turn: `Schema:\\n<canonical schema>\\n\\nQuestion: <question>`. Assistant turn: bare SQL.
About {aug_pct}% of training schemas have extra unrelated tables added
(label-preserving, re-executed) to teach schema linking in larger databases.

## Limitations
Synthetic questions; single-turn; SELECT only; SQLite dialect; reference answers come from the
sources and are only checked by execution, not by a human.
"""


def push_dataset(processed: Path, eval_path: Path, card: str, repo_id: str, token: str) -> str:
    from huggingface_hub import HfApi

    stage = processed / "_hub_stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    shutil.copy(processed / "train.jsonl", stage / "train.jsonl")
    shutil.copy(processed / "val.jsonl", stage / "validation.jsonl")
    shutil.copy(processed / "records.parquet", stage / "all_records.parquet")
    shutil.copy(eval_path, stage / "test_heldout.jsonl")
    (stage / "README.md").write_text(card)
    api = HfApi(token=token)
    api.create_repo(repo_id, repo_type="dataset", exist_ok=True)
    api.upload_folder(folder_path=str(stage), repo_id=repo_id, repo_type="dataset")
    shutil.rmtree(stage)
    return f"https://huggingface.co/datasets/{repo_id}"
