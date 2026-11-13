# ETL tests (`tests/`)

Tests run **offline** on fixtures: no downloads, under 10 s, and they run in CI.

| File | Cases |
|---|---|
| `conftest.py` | ~12 fixture rows: good, MySQL `YEAR()` (repairable), ambiguous column (id 5097 copy), missing column, `CREATE SCHEMA` context, `public.` qualified context, WITH…DELETE (not select), exact duplicate, conflicting label, relative-time with hard-coded date, empty result, sqlcc-style no-data context. Also a tiny two-domain Parquet file and a JSON file built in `tmp_path` |
| `test_schema.py` | canonicalize is deterministic; FK rendering; quoting of odd identifiers; sample-row truncation; the Chinook golden file |
| `test_validate.py` | each fixture → expected `status`/`drop_reason`; the repaired row executes; `validation_level` is `schema` for the no-data context; the timeout path (a recursive CTE that never ends) → `TIMEOUT` within about 2 s |
| `test_dedup_split.py` | survivors of the dedup passes; empty domain intersection; leakage guard removes from train, not test; seeded split is stable |
| `test_pipeline_idempotent.py` | run the pipeline on the fixtures twice → identical sha256 of `train.jsonl`, `records.parquet` (content hash) and the eval file; second-run stats `new=0`; `--limit` then full → `new` equals the remainder |
| `test_prompt.py` | `build_messages` format; `extract_sql` handles fences, "SQL:" prefixes, trailing explanation, multiple statements (takes the first), leading whitespace |
| `test_sqlexec.py` / `test_score.py` | see `04-evaluation/metrics.md` (column order, numeric strings, datetime normalization, ordered vs unordered) |

The CI job (`.github/workflows/ci.yml`): `uv sync --group dev --group etl --group eval` → `ruff check` → `pytest -q`. Target: under 2 minutes.
