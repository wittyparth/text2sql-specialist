# Website spec: Gradio app (`src/text2sql/app/`)

Goal: a reviewer **checks the claim themselves** in under 60 seconds.

## Tab 1: "Try it" (default)

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│ Text-to-SQL Specialist · base vs fine-tuned Qwen2.5-Coder-1.5B · CPU only        │
│ [banner while warming: "Models warming up (~1 min after a cold start)…"]         │
├───────────────────────────────────────────────────────────────────────────────────┤
│ Database: (•) Chinook – music store, 11 tables                                    │
│           ( ) Unseen domain A   ( ) Unseen domain B   ( ) Unseen domain C         │
│           ( ) Paste your own schema                                               │
│ ▸ Show schema (accordion → canonical schema in a code block)                      │
│ [custom DDL textbox – only visible for "Paste your own schema"]                   │
│ Question: [______________________________________________] [Generate & run ▶]    │
│ Examples: chips from the eval set for this DB (each has a reference answer)       │
├──────────────────────────────────────┬────────────────────────────────────────────┤
│ Base model                           │ Fine-tuned (ours)                          │
│ ```sql SELECT … ```                  │ ```sql SELECT … ```                        │
│ ❌ no such column: T1.TrackId · 1.3s  │ ✅ executed · 25 rows · 1.2s               │
│                                      │ ✅ matches reference answer                │
│ (empty)                              │ [result table, ≤ 50 rows]                  │
└──────────────────────────────────────┴────────────────────────────────────────────┘
│ Reference SQL (only for example questions, collapsed)                             │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### Preset databases (`data/demo/`, committed, small)
- `chinook.sqlite` (1.07 MB).
- 3 `*.sqlite` files built by the pipeline from **held-out test domains** (rows re-created from `context_sqlite`; pick the 3 domains with the richest multi-table contexts). The label says "a domain the model never saw in training".
- Example chips per database: 8 for Chinook (mix of difficulties, **include at least 3 the base model gets wrong**; we know which from the baseline run) and 5 per held-out domain, taken from the eval files with their reference SQL.

### Behavior
1. Pick a database → load the canonical schema (cached in memory at startup).
2. Click Run → build the messages → call both endpoints (concurrently by default) → extract → run read-only → render.
3. If the question came from an example chip → also run the reference SQL and show the match badge using **the same `results_match` as the eval** (metric parity).
4. Errors are shown as data (red badge with the SQLite message), never as a stack trace.
5. `gr.Blocks().queue(default_concurrency_limit=2)`. The question is capped at 500 chars and custom DDL at 20 KB.

### Custom schema flow
- Parse with `sqlglot` and **allow only `CREATE TABLE` and `INSERT`** statements. Otherwise show a friendly error.
- `executescript` into a fresh in-memory database (2 s timeout) → `canonicalize` → same flow. There's no reference, so no match badge.
- Note under the box: "First query on a new schema is slower (no prompt cache yet)."

## Tab 2: "Results"
Renders `reports/eval_results.md` and the figures: headline table, paired comparison, per-difficulty chart, quantization chart, error-class shift. Links to the W&B run, the model repo and the dataset.

## Tab 3: "Data pipeline"
- The funnel table and drop-reason chart from `reports/data_quality.json`.
- **"Browse dropped rows"**: a dropdown of reasons, showing 3 real examples each (question, SQL, SQLite error).
- The headline example: Gretel id 5097, ambiguous `GROUP BY`.

## Tab 4: "About"
- What and why in 5 bullets, the architecture diagram (PNG rendered from `05-serving-and-app/architecture.md`), how to run locally (`docker compose up`, native Mac), and links.

## Config (env vars)
`LLM_BASE_URL`, `LLM_FT_URL`, `LLM_BASE_MODEL`, `LLM_FT_MODEL` (sent as `model` on every request; required by Ollama and OpenRouter, ignored by llama-server), `APP_SEQUENTIAL` (0/1), `APP_MAX_ROWS` (50), `REQUEST_TIMEOUT_S` (60). Backends and the one-step runner: see `local-run.md`.

## Acceptance
- [ ] With both containers up, an example chip → both columns render in under 3 s warm (Mac Docker).
- [ ] Pasting `DROP TABLE x;` as the schema → rejected. A model output of `DELETE …` → blocked by the authorizer with a clear message.
- [ ] Killing `llm-base` → the base column shows "model unavailable" and the fine-tuned column still works.
