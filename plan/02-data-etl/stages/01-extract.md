# Stage 01: Extract (`etl/extract.py`)

**Input:** `configs/pipeline.yaml` sources block.
**Output:** files in `data/raw/{source}/{revision}/…` and a manifest entry per file `{revision, sha256, bytes, fetched_at}`.

## Rules
1. HF files: `hf_hub_download(repo_id, filename, repo_type="dataset", revision=<pinned sha>, local_dir=data/raw/{source}/{revision})`.
2. Chinook: HTTPS GET of the pinned release asset into `data/raw/chinook/{tag}/`.
3. **Skip if present** and the sha256 matches the manifest. A run with no new or changed files logs `extract: 0 downloaded, 4 cached`.
4. **Retry:** 3 attempts, backoff 1s / 4s / 16s, on network errors and 5xx. After download, verify the size is > 0 and parse-check the file (pyarrow can open the Parquet; the JSON loads; SQLite has `sqlite_master` with 11 tables).
5. **Atomic:** download to `*.part`, verify, then `os.replace`.
6. A pinned revision that **changes** (you bumped the config) means a new folder. Old records stay; new rows flow through as incremental. That's the "source updated" story.

## Readers (streaming-friendly)
- Gretel: `pyarrow.parquet.ParquetFile(...).iter_batches(10_000)`, yielding dict rows.
- sqlcc: `json.load` (21 MB, fine in memory). Note in the code that `ijson` would stream it at larger scale.
- Each yielded row carries a `source_row_key`. Rows whose key is already in the manifest are **skipped before mapping**. This is the incremental mechanism.

## `--limit N`
Caps rows per source (taken in file order). Used for the incremental demo and for fast dev loops.

## Acceptance
- [ ] A fresh run downloads 4 files. A second run downloads 0.
- [ ] Deleting one raw file causes only that file to be re-downloaded.
- [ ] A corrupted `.part` file (simulated in a test) is never promoted.
