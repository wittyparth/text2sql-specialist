# Verified facts (measured 2026-11-13)

Everything here was run, downloaded or checked today. Scripts that produced these numbers live in the session scratchpad and become `src/text2sql/etl/validate.py` and `scripts/profile_sources.py` in the repo.

## Source 1 — `gretelai/synthetic_text_to_sql` (Apache-2.0)

- Files: `synthetic_text_to_sql_train.snappy.parquet` (100,000 rows, 32 MB), `synthetic_text_to_sql_test.snappy.parquet` (5,851 rows).
- Columns: `id, domain, domain_description, sql_complexity, sql_complexity_description, sql_task_type, sql_task_type_description, sql_prompt, sql_context, sql, sql_explanation`.
- `sql_context` contains `CREATE TABLE` **and `INSERT`** statements, so queries can be run and their **results** checked.
- **100 domains**, 576 to 1,368 rows each, which makes a domain-level split practical.
- Task types (train): analytics & reporting 88,186 · data manipulation 9,665 · data retrieval 1,309 · data definition 840.

### Execution validation on all 100k train rows (SQLite, in memory, 14 s total)

| Outcome | Rows | % |
|---|---|---|
| Runs as-is | 76,329 | 76.3% |
| Recovered by `sqlglot` transpile (mysql/postgres → sqlite) | 3,369 | 3.4% |
| Schema (context) fails to load | 2,817 | 2.8% |
| SQL fails even after transpile | 17,485 | 17.5% |
| **Of all usable rows: non-empty result** | 59,968 | 60.0% |
| **Of all usable rows: empty result** | 19,730 | 19.7% |

Top failure reasons (test split, 5,851 rows): `no such column` 293 · `no such function` 211 · `no such table` 158 · syntax near `FROM` 94 · `CREATE SCHEMA` in context 91 · `ambiguous column name` 36.

Pass rate by complexity (test split): basic 88% · aggregation 78% · single join 72% · window functions 71% · set operations 71% · multiple joins 71% · subqueries 64% · CTEs 0/19 (needs investigation in the validate stage; likely multi-statement or DML CTEs).

Concrete bad row (train file, id 5097): `GROUP BY salesperson_id` after a join, which SQLite rejects as **ambiguous**. Use it as the README example.

Size: prompt + schema + SQL, raw characters p50 454 / p90 728 / p99 1,051 / max 2,295.
With the **canonical schema format** (see decisions D4): p50 345 / p90 541 / p99 771 / max 1,002 characters, about 250 tokens at p99.

Duplicates: 195 normalized-question duplicates in train.

## Source 2 — `b-mc2/sql-create-context` (CC-BY-4.0)

- One file: `sql_create_context_v4.json`, 78,577 rows, fields `question, context, answer`.
- `context` is `CREATE TABLE` only, **with no data**, so validation can only check that the query parses and binds to the schema, not its result.
- Executes in SQLite: 76,910 ok · 294 context fails · 1,373 SQL fails.
- 326 normalized-question duplicates; only 2 questions overlap with Gretel.
- Origin: WikiSQL and Spider, mostly single-table and short. Useful for format diversity, not for difficulty.

## Source 3 — Chinook SQLite database

- `https://github.com/lerocha/chinook-database/releases/latest/download/Chinook_Sqlite.sqlite` (1.07 MB).
- 11 tables: Album 347 · Artist 275 · Customer 59 · Employee 8 · Genre 25 · Invoice 412 · InvoiceLine 2,240 · MediaType 5 · Playlist 18 · PlaylistTrack 8,715 · Track 3,503.
- Raw `CREATE` statements total 4,138 characters. In the canonical format with 2 sample rows per table, 3,375 characters (about 1,000 tokens). This is longer than any training prompt; see risk R7.
- Role: **out-of-distribution eval only** (a real multi-table, foreign-keyed business schema). Never used in training.

## Model

- `Qwen/Qwen2.5-Coder-1.5B-Instruct`, `unsloth/Qwen2.5-Coder-1.5B-Instruct-bnb-4bit` and the official `Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF` (includes `q4_k_m`) all exist on the HF Hub.
- The newer Qwen3.5 small models (0.8B/2B/4B) are a **hybrid Mamba** architecture. They need transformers v5 and are slow to compile on a T4; a known issue reports dynamo recompile errors on the 2B, and **Unsloth advises against QLoRA on them**. See decision D2.

## Tooling

- TRL v1.16 `SFTConfig` supports `assistant_only_loss`, `max_length`, `packing`. Unsloth's `train_on_responses_only(trainer, instruction_part="<|im_start|>user\n", response_part="<|im_start|>assistant\n")` handles the Qwen chat template.
- Unsloth export: `model.save_pretrained_gguf(dir, tokenizer, quantization_method="q4_k_m")`, `model.push_to_hub_gguf(repo, tokenizer, quantization_method=...)`; also supports `q8_0` and `f16`.
- `sqlglot` 30.31.0: transpile works, but some constructs are unsupported (`CREATE SCHEMA`, `AUTO_INCREMENT` inside a table, `TO_CHAR` format, `PIVOT`, `INTERSECT ALL`). These fall into the "unrecoverable" bucket.
- llama.cpp `llama-server`:
  - `-hf <user>/<repo>[:quant]` downloads a GGUF straight from the HF Hub (defaults to Q4_K_M) and serves an OpenAI-compatible `/v1/chat/completions` and `/health`.
  - The official Docker image `ghcr.io/ggml-org/llama.cpp:server` is published for **linux/amd64 and linux/arm64**, so it runs natively on Apple Silicon with Docker.
- `llama-cpp-python` 0.3.35's **prebuilt Metal wheel is corrupt** ("trailing contents after end-of-central-directory"). Building from source works but is slow. Decision D7 avoids it entirely.

## Base model behaviour (Qwen2.5-Coder-1.5B-Instruct, Q4_K_M, temperature 0, canonical-schema prompt)

| Eval | n | Execution accuracy | Notes |
|---|---|---|---|
| Gretel test, random valid rows | 200 | **62.0%** (61.5% with column-order-strict compare). *Measured with 4 parallel slots, so ±a few pts; re-measure one request at a time* | 11 execution errors: no such column 6, no such table 3, no such function 1 (`YEAR()`), ambiguous 1. Weakest: aggregation 17/42, single join 9/21, window 0/2 |
| Chinook (100 items, subagent-built) | 100 | **59% deterministic** (one request at a time). The 62% from 4 parallel slots is an artifact | parallel run: easy 23/25 · medium 21/35 · hard 9/25 · sqlite_specific 9/15. **All errors are `no such column`**: T1/T2 alias mix-ups and invented join paths (e.g. `InvoiceLine.MediaTypeId`) |

- It never wraps output in code fences (0/200) with this system prompt. The extractor still handles fences for fairness.
- Prompt sizes: Gretel p50 **120 tokens**; Chinook **1,339 tokens**.
- Time-dependent questions ("last 6 months") have hard-coded dates in the reference SQL, so they're ill-defined. The base model got 0/4 of those.

## Determinism (measured on the 100 Chinook items, same GGUF, temperature 0)
| Backend / concurrency | EX | SQL identical to llama-server one-at-a-time |
|---|---|---|
| llama-server, one at a time (run twice) | 59 | 100/100 (deterministic across reruns) |
| **Ollama** 0.40.16, one at a time (Modelfile `num_ctx 8192`, `temperature 0`) | 59 | **100/100**. Ollama is a drop-in backend |
| Ollama, 4 concurrent requests | 59 | 100/100 (they were run one at a time) |
| llama-server, **4 parallel slots** | 62 | **95/100**. Batched computation flips about 5% of greedy outputs |

→ **Evals must send one request at a time** (or use `-np 1`). Parallel slots are fine for the demo but make scores non-reproducible.
- Ollama: `ollama pull hf.co/<user>/<repo>:Q4_K_M` **works** (verified). Its chat template prompt matches llama-server exactly (1,339 prompt tokens for Chinook in both). Default context is 4,096; the API can't change it, so a Modelfile `num_ctx` is required. Setting `repeat_penalty 1.0`/`top_k 1` made no difference at temperature 0.

## Serving measurements

- **Metal (M5), Q4_K_M, 4 slots:** p50 0.38 s and p95 1.0 s per Gretel item; 200 items in 23 s. Chinook p50 0.93 s.
- **Docker, `--cpus 2`, `-t 2`** (simulating the free HF Space):
  - First Chinook request **12.4 s** (prefill 110 tok/s over 1,337 tokens).
  - **Repeat requests 1.3 s**: 1,325 of 1,339 prompt tokens were reused from the slot's prompt cache. Generation runs at 40 tok/s.
  - Small schema: 0.9 s.
- **Context sizing bug found:** `-c 4096 -np 4` → HTTP 500 "Context size has been exceeded" on Chinook. Rule: `-c ≥ n_parallel × (max_prompt + max_tokens)`.
- The llama.cpp server image is Ubuntu 26.04.1 LTS, runs as root, entrypoint `/app/llama-server`, and ships `apt-get`, `python3` and `curl`. It's 1.17 GB. Pin it by digest: `ghcr.io/ggml-org/llama.cpp:server@sha256:2103d1f4f2e2e223ad80587dcb39fc15a9f912f29ae1fa9fc1193fe8c1aea82f` (build b12316, 2026-11-12).
- The HF cache stores GGUFs as **symlinks into `blobs/`**, so mount the whole `models--…` folder (or use `-hf`), not the `snapshots/` folder alone.

## Chinook eval set (built by subagent, validated)

- `data/eval/chinook_eval.jsonl`: 100 items. easy 25 · medium 35 · hard 25 · sqlite_specific 15. All 11 tables covered.
- `data/eval/validate_chinook_eval.py`: checks that each item is read-only, runs, is non-empty and has a stable row count; checks determinism under extra sort keys and that there are no ties at top-N cutoffs. Result: **100/100 pass**, 3 warnings, each reviewed: the question states its tie-break.
- Known strictness traps: year as text vs integer (chinook-086), raw datetime vs `date()` (055), 94 vs 94.0 (098). The value normalization in `04-evaluation/metrics.md` handles all three.

## Hosting
- HF docs list Spaces **CPU Basic: 2 vCPU / 16 GB**, sleeping when idle (third-party guides say after 48 h of inactivity, unconfirmed). Docker Spaces route to `app_port` (default 7860) and expose a single port.
- **Conflict:** mid-2026 community threads report that running Gradio/Docker Spaces on cpu-basic now needs a paid plan, and that new accounts see a quota of 0. **Not verified for your account.** That's task T6.0.

## Machine

- Apple M5, 16 GB RAM, Docker via **OrbStack** (must be running to use `docker`), Homebrew `llama.cpp` installed, `uv` installed, Python 3.12 available at `/opt/homebrew/bin/python3.12`.
- Training GPU: **free Colab or Kaggle T4** (16 GB, **fp16 only, no bf16**).
