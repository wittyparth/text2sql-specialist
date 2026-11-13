# Decisions log (ADR-style)

Each decision records: **choice → why (with evidence) → what we rejected → what would change our mind.** This file becomes the "Design decisions" section of the final README; it's the part that shows judgment.

---

## D1. Use case: text-to-SQL (SQLite, SELECT-only)
- **Why:** SQL can be **verified by running it**. That gives (a) a real validation step in the ETL and (b) an objective eval (execution accuracy) instead of an LLM judge. It's also an enterprise-relevant task: NL interfaces to company data.
- **SELECT-only:** 88% of Gretel rows are analytics/reporting. Write queries (UPDATE/DELETE) would need DB-state comparison and a riskier demo. Out of scope; the reason is documented.
- **Rejected:** a generic domain chatbot (fuzzy eval) and a classifier (narrower fine-tuning story).

## D2. Base model: `Qwen2.5-Coder-1.5B-Instruct`
- **Why:**
  - It's a code-pretrained instruct model, so we start from a reasonable baseline.
  - It's a dense transformer that is mature in Unsloth, TRL and llama.cpp, so export and serving carry low risk.
  - At 1.5B it trains in minutes on a T4 and runs on a **2-vCPU free CPU**.
- **Measured baseline:** **62.0% execution accuracy** on 200 random valid rows of the Gretel test split, p50 latency 0.38 s on an M5 (Metal, Q4_K_M). There is real room to improve.
- **Rejected:**
  - **Qwen3.5 0.8B/2B/4B (newer):** hybrid Mamba, needs transformers v5, slow T4 compile, reported recompile errors, and Unsloth itself discourages QLoRA on it. *Choosing stability over recency under a one-day deadline is the point. Say this in the interview.*
  - **7B models:** won't run acceptably on a free CPU Space.
- **Would change if:** a paid GPU becomes available, in which case try Qwen3.x 4B with bf16 LoRA.

## D3. Three heterogeneous sources (Parquet + JSON + live SQLite DB)
- **Why:** proves real extraction, schema mapping and cross-source dedup, not "download one parquet file".
- Gretel = volume plus result-level validation. sql-create-context = format diversity, with schema-level validation only (it has no data). Chinook = a real business DB used **only for out-of-distribution eval**.

## D4. One canonical schema format for every source (and the app)
- **Problem measured:** raw schemas differ per source (MySQL-isms, `INSERT` statements, varied whitespace). Chinook's raw DDL is about 4× longer than the training p99.
- **Choice:** load every schema into SQLite, then **write it back out from SQLite metadata** (`PRAGMA table_info` and `foreign_key_list`) into one compact form: `CREATE TABLE t (col TYPE [PRIMARY KEY] [REFERENCES x(y)], ...);` plus up to **2 sample rows per table** as `-- v1, v2` comments (values truncated to 30 characters).
- **Why:**
  - Training, eval and the live app all see *exactly* the same format, which is the shared prompt contract.
  - It removes dialect noise from inputs.
  - Sample rows teach value formats (dates, enum strings), which the base-model failures showed it needs.
- **Same function** (`text2sql.schema.canonicalize`) is used by the ETL, the eval and the app.

## D5. Dialect repair with `sqlglot`, not dropping
- Rows that fail are retried with `transpile(read="mysql"|"postgres", write="sqlite")` and re-executed. That **recovers 3,369 rows (3.4%)**. Only rows that still fail are dropped, with a recorded reason.
- Teaches the model the SQLite dialect. Base-model failures include `YEAR()`, a MySQL function SQLite doesn't have.

## D6. Split by **domain**, not by row
- Gretel rows in the same domain share table templates and phrasing. A random row split leaks near-duplicates into test.
- 100 domains: **10 held-out test domains, 5 validation domains, 85 train**, seeded and recorded in the dataset card.
- sql-create-context: training only (it can't be result-validated).
- Chinook: eval only.

## D7. Serving: llama.cpp `llama-server` (official Docker image), app talks OpenAI-compatible HTTP
- **Why:**
  - **No compile step:** the `llama-cpp-python` Metal wheel was corrupt today, and source builds are slow.
  - **Multi-arch image** (arm64 + amd64), so it runs on Mac and Linux.
  - `-hf repo:Q4_K_M` pulls the model straight from the Hub.
  - Because the API is OpenAI-compatible, **the same eval harness and app work against llama-server, Ollama, LM Studio or OpenRouter** with only a base-URL change.
- **Rejected:**
  - `llama-cpp-python` inside the app: build fragility.
  - vLLM: needs a GPU.
  - Paid inference endpoints: cost.

## D8. Eval runs against **GGUF via llama-server**, i.e. the artifact we actually ship
- We evaluate F16, Q8_0 and Q4_K_M GGUFs of both the base and fine-tuned models on the Mac (Metal). We report the quantization cost and evaluate exactly what users get.
- **Determinism:** evals send **one request at a time**. Measured: 4 parallel slots changed 5/100 greedy outputs (Chinook EX 62 vs 59). Running one at a time gives identical output across reruns **and** across llama-server and Ollama.

## D9. Execution-accuracy comparison rules (fairness)
- Results are compared as **multisets of rows, where each row's values are compared regardless of column order**. Floats are rounded to 4 decimal places. Order is enforced only when the reference SQL has a top-level `ORDER BY` *and* the item is flagged `order_matters`.
- **Measured:** strict column-order comparison under-counted the base model (61.5% → 62.0%).
- Base and fine-tuned outputs go through the **same SQL extractor**: strip code fences and prefixes, take the first statement.
- **Time-dependent items** (reference uses `now`/`CURDATE`/relative dates) are **excluded from the eval sets** and counted in the quality report. The reference is ill-defined: e.g. "last 6 months" stored as `'2022-01-01'`.

## D10. Training: QLoRA SFT with Unsloth + TRL, loss on assistant tokens only
- 4-bit base, LoRA r=16 on all linear layers, fp16 (a T4 has no bf16), adamw_8bit, 1 epoch over about 10k examples.
- Loss only on the SQL (`train_on_responses_only`). The model shouldn't spend capacity learning to predict schemas.
- **Rejected:**
  - Full fine-tuning: VRAM and time.
  - DPO in this round: time. The design is in `03-training/next-steps-dpo.md`.

## D11. Experiment tracking: W&B (public run link)
- The reviewer can open the live curves, which a screenshot doesn't prove. MLflow was considered, but a local MLflow server isn't shareable.
- We still log the config, dataset revision and git SHA into the run, which is the reproducibility story.

## D12. Demo hosting: HF Docker Space (CPU, 2 vCPU / 16 GB), with a verified fallback chain
- Same container stack as local `docker compose`.
- **Uncertainty found:** the docs say CPU Basic is free, but mid-2026 community reports say running a Docker Space now needs PRO. Check this before building the Space (T6.0).
- Fallback chain: free Space → PRO (about $9/month, cancel afterwards) → Mac + `docker compose` + Cloudflare quick tunnel (free, live only while the Mac is on).
- `docker compose up` is always the permanent, reviewer-runnable path, whichever hosting option works.
- Free Spaces sleep when idle, so the first request after a cold start is slow. Documented in the README.

## D13. Eval set for Chinook generated by a Claude Code subagent, then validated by execution
- Every item is executed. Determinism is checked (no ties at top-N cutoffs, non-empty results). Difficulty mix: easy/medium/hard/sqlite_specific. A human spot-checks 20 items before it's frozen.
- It's committed to the repo (`data/eval/chinook_eval.jsonl`) and frozen; it never feeds training.

## D14. Package manager & runtime: `uv` + Python 3.12, `src/` layout, `pyproject.toml`
- `uv.lock` gives fast, reproducible installs. The same lockfile is used in Docker.

## D15. Implementation deviations from the stage specs (found while building T1, 2026-11-13)
Each one has a test or a measurement behind it.
- **Composite primary keys** are written as a table-level `PRIMARY KEY (a, b)`. Per-column `PRIMARY KEY` is invalid SQL for Chinook's `PlaylistTrack`, which broke the round-trip acceptance check. Chinook's canonical schema is now 3,386 characters (was 3,375), so every baseline measured with the prototype format has to be re-measured with the final harness (CLAUDE.md §4 already requires this).
- **`YEAR()` / `MONTH()` / `DAY()` get an explicit AST rewrite** to `CAST(STRFTIME(...) AS INT)`. sqlglot's SQLite generator leaves them untouched and SQLite has no such functions, so plain `transpile` recovered none of them. The rewrite recovers about 2,200 `YEAR` rows in Gretel.
- **`'-N WEEK'` date modifiers are rewritten to days.** SQLite doesn't know weeks and returns NULL without an error, so "it executed" was not proof the label was right (214 rows).
- **Processed row keys come from `data/interim/validated.parquet`, not from the manifest.** That table is written before the manifest, so the two can never disagree after a crash. The manifest keeps file fingerprints and run history.
- **Sampling happens before augmentation** (spec order was augment → sample). Same distribution, about 3.3k augmentations instead of about 20k. Augmented rows replace their originals in `records.parquet`.
- **A row whose augmentation fails re-execution is kept un-augmented** (and counted as `AUG_FAILED` in the report) instead of being dropped. No training data is lost for a harmless reason.
- **Leakage guard compares lowercase-and-collapsed SQL text**, not the sqlglot-normalized form: it's cheap, and only identical text can leak. It removed 42 rows.
- **The ambiguous-`GROUP BY` headline row is `gretel:train:5097`**, not a test-split row as `verified-facts.md` first said.
- `schema.load_context` stays plain (`executescript`). The dialect pre-clean and transpile fallback live in `etl/validate.py`, because only the ETL needs sqlglot and the app image doesn't ship it.
