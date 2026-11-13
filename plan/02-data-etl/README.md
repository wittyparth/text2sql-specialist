# ETL pipeline: overview

## What it produces
| Output | Location | Consumer |
|---|---|---|
| `records.parquet`: **every** row from every source, including dropped rows with `status` and `drop_reason` (auditable) | `data/processed/` | report, debugging, HF dataset `all` config |
| `train.jsonl`, `val.jsonl`: chat-format messages plus `meta` | `data/processed/` → HF Hub | Colab training |
| `gretel_heldout_eval.jsonl`: frozen test set from the held-out domains | `data/eval/` (committed) | eval harness |
| `data_quality.md` / `.json`: per-stage funnel, drop reasons with examples, distributions, leakage checks, input revisions | `reports/` (committed) | README, app "Data pipeline" tab |

## DAG

```
extract ──► map ──► validate+repair ──► canonicalize ──► filter ──► dedup ──► split ──► augment ──► sample ──► load ──► report
 (raw files)  (unified   (run in SQLite,     (schema →        (scope,    (exact,   (by       (distractor (stratified  (parquet,
              Record)    sqlglot fallback)   compact DDL)     tokens,    question, domain)  tables,      mix)        jsonl, hub)
                                                              time-dep)  leakage)           train only)
```

Stage specs, each with input, output, rules, edge cases and acceptance checks:
[`stages/01-extract.md`](stages/01-extract.md) · [`02-map.md`](stages/02-map.md) · [`03-validate-repair.md`](stages/03-validate-repair.md) · [`04-canonicalize.md`](stages/04-canonicalize.md) · [`05-filter.md`](stages/05-filter.md) · [`06-dedup.md`](stages/06-dedup.md) · [`07-split.md`](stages/07-split.md) · [`08-augment.md`](stages/08-augment.md) · [`09-sample-load.md`](stages/09-sample-load.md)

## Engineering properties (each one is demonstrable, not just claimed)

| Property | How | How it's shown |
|---|---|---|
| **Idempotent** | Record id = content hash. Writes are upserts keyed by id. Stages write to a temp file then `os.replace` (atomic). Seeds are fixed. Outputs are sorted by id | `test_pipeline_idempotent.py`: run twice → identical output hashes; the second run logs `new=0` |
| **Incremental** | `data/state/manifest.json` stores per-source `{revision, file_sha256, rows_seen}` plus the set of processed `source_row_key`s. Only new rows go through map/validate (the expensive stages). Downstream stages recompute from the full records table (cheap, deterministic) | `make pipeline-demo-incremental`: `--limit 50000` then a full run, which logs `new=50000 skipped=50000` |
| **Retries** | Downloads: 3 attempts with exponential backoff (1s, 4s, 16s), and the sha256 is checked after download. Per-row SQLite work has a 2 s timeout via `set_progress_handler`, so one bad row can't hang the run | fault-injection unit test (mocked download fails twice, then succeeds) |
| **Reproducible** | HF files pinned to a **commit revision** in `configs/pipeline.yaml`; revisions, file hashes, the sqlglot version and the git SHA are written into the report and the dataset card | the report header |
| **Observable** | Each stage logs `in / out / dropped-by-reason / seconds` into a `StageStats` object, and `report.py` renders them | the funnel table in `data_quality.md` |
| **Auditable** | Dropped rows are kept in `records.parquet` with a reason. The report shows 3 real examples per reason | the "Drop reasons" section |

## Runtime budget
Measured: validating 100k Gretel rows takes **14 s** on the M5, and sql-create-context (78k rows) is similar. A full pipeline run, including token counting, is expected to take **under 3 minutes**. Use 8 processes for validation only if it's slower than that.

## CLI
```
python -m text2sql.etl.pipeline run [--config configs/pipeline.yaml] [--limit N] [--only-stage NAME] [--push]
python -m text2sql.etl.pipeline status      # prints manifest: sources, revisions, rows processed, last run
```
