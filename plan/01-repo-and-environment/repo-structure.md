# Repository structure

The repo root is `~/Code/Fine tuning/` (GitHub name: **`text2sql-specialist`**). Every file has one job. If a file isn't listed here, it shouldn't exist.

```
text2sql-specialist/
├── README.md                     # Results table + live demo link on the first screen (see 06-deliverables/readme-outline.md)
├── LICENSE                       # Apache-2.0 (compatible with Gretel Apache-2.0 + sql-create-context CC-BY-4.0 attribution in dataset card)
├── pyproject.toml                # uv project; deps grouped: core / etl / eval / app / dev
├── uv.lock
├── Makefile                      # The single entry point for humans (see environment.md)
├── .env.example                  # HF_TOKEN=, WANDB_API_KEY=, OPENROUTER_API_KEY= (all optional except for publishing)
├── .gitignore                    # data/raw, data/interim, data/processed, .env, *.gguf, .venv, __pycache__
├── .dockerignore
├── configs/
│   ├── pipeline.yaml             # sources (repo, file, revision), filters, split seeds, sample sizes, augmentation rates
│   ├── train.yaml                # hyperparameters, read by the Colab notebook (copied/printed into W&B config)
│   └── eval.yaml                 # endpoints (base/ft URLs, model names), eval sets, parallelism, max_tokens
├── src/text2sql/
│   ├── __init__.py
│   ├── prompt.py                 # SYSTEM_PROMPT, build_messages(schema, question), extract_sql(text) — THE shared contract
│   ├── schema.py                 # canonicalize(conn, sample_rows=2) -> str ; load_context(ddl) -> conn (with transpile fallback)
│   ├── sqlexec.py                # safe_connect(), run_select(conn, sql, timeout_s, max_rows) ; results_match(pred, gold, ordered)
│   ├── etl/
│   │   ├── __init__.py
│   │   ├── records.py            # Record dataclass (unified schema) + make_id()
│   │   ├── manifest.py           # state file: processed source fingerprints + record ids (idempotency/incremental)
│   │   ├── extract.py            # download pinned HF files + Chinook db into data/raw (cached by revision/hash)
│   │   ├── mappers.py            # map_gretel(row), map_sqlcc(row) -> Record
│   │   ├── validate.py           # execution validation + sqlglot repair + drop-reason taxonomy
│   │   ├── filters.py            # scope (SELECT-only), length/token budget, time-dependence flag
│   │   ├── dedup.py              # exact id, normalized question+schema, normalized SQL
│   │   ├── augment.py            # distractor-table schema augmentation (long-schema robustness)
│   │   ├── split.py              # domain split + stratified sampling
│   │   ├── load.py               # Parquet (all records + status), chat JSONL (train/val), eval JSONL, HF push
│   │   ├── report.py             # writes reports/data_quality.md + reports/data_quality.json
│   │   └── pipeline.py           # CLI: `python -m text2sql.etl.pipeline run [--limit N] [--push]`
│   ├── eval/
│   │   ├── __init__.py
│   │   ├── client.py             # OpenAI-compatible chat client (llama-server / Ollama / OpenRouter), retries, timing, usage
│   │   ├── run.py                # CLI: run one model over one eval set -> runs/<run_id>/predictions.jsonl
│   │   ├── score.py              # execution accuracy, valid-SQL rate, per-difficulty, bootstrap CIs, paired diff
│   │   ├── compare.py            # builds reports/eval_results.md + JSON from several runs
│   │   └── errors.py             # error taxonomy (rule-based) for failed predictions
│   └── app/
│       ├── __init__.py
│       ├── main.py               # Gradio Blocks app (tabs: Try it / Results / Data pipeline / About)
│       ├── databases.py          # preset DBs: Chinook + 3 held-out-domain sample DBs; custom-schema loader
│       └── warmup.py             # primes llama-server prompt cache for each preset DB × model at startup
├── data/
│   ├── raw/                      # (gitignored) downloaded source files, keyed by revision
│   ├── interim/                  # (gitignored) per-stage parquet checkpoints
│   ├── processed/                # (gitignored) final parquet + jsonl; published to HF Hub instead
│   ├── state/manifest.json       # (gitignored) idempotency state
│   ├── demo/                     # (committed) chinook.sqlite + 3 small sample .sqlite files for the app
│   └── eval/                     # (committed, frozen) chinook_eval.jsonl, validate_chinook_eval.py, gretel_heldout_eval.jsonl
├── notebooks/
│   └── train_qlora_colab.ipynb   # written BY YOU (see 03-training/colab-notebook.md); outputs kept for proof
├── reports/                      # (committed, generated) data_quality.md/json, eval_results.md/json, figures/*.png
├── runs/                         # (gitignored except summary) eval predictions per run
├── scripts/
│   ├── profile_sources.py        # the profiling that produced verified-facts.md (kept for transparency)
│   ├── prototypes/               # ✅ exists: today's probe scripts (check, profile, canon, base/chinook probes, chinook eval builder)
│   ├── export_gguf_local.sh      # fallback: merge LoRA + convert to GGUF with llama.cpp on the Mac
│   ├── build_demo_dbs.py         # writes data/demo/*.sqlite for 3 held-out domains (from pipeline output)
│   └── deploy_space.py           # assembles the Space folder + HfApi().upload_folder(repo_type="space")
├── docker/
│   ├── app.Dockerfile            # python:3.12-slim + uv; runs ETL / eval / app
│   ├── space.Dockerfile          # single container for HF Space: llama.cpp image + uv + app + 2 llama-servers
│   └── space-entrypoint.sh       # starts llm-base, llm-ft (ports 8081/8082), waits for /health, warms cache, starts Gradio on 7860
├── docker-compose.yml            # services: llm-base, llm-ft, app ; profiles: etl, eval, app-only (app → host backends)
├── run.sh                        # ONE-STEP local run: auto-picks Ollama → native llama.cpp → Docker (05-serving-and-app/local-run.md)
├── ollama/
│   ├── base.Modelfile            # FROM hf.co/Qwen/...:Q4_K_M + num_ctx 8192 + temperature 0
│   └── ft.Modelfile              # same for the fine-tuned GGUF
├── tests/
│   ├── conftest.py               # tiny fixture rows (good, broken, mysql-dialect, duplicate, time-dependent)
│   ├── test_schema.py
│   ├── test_sqlexec.py
│   ├── test_prompt.py
│   ├── test_validate.py
│   ├── test_dedup_split.py
│   ├── test_pipeline_idempotent.py
│   └── test_score.py
├── .github/workflows/ci.yml      # ruff + pytest + pipeline on fixtures (no downloads) on every push
└── plan/                         # this plan (kept in repo: shows how the work was approached)
```

## Rules that keep the codebase good

1. **One shared contract module:** `prompt.py`, `schema.py` and `sqlexec.py` are imported by the ETL, eval and app. They are never copy-pasted. The Colab notebook needs no import because the training JSONL already contains the rendered messages.
2. **Configs drive behavior.** No magic numbers in code. Seeds, sizes and rates live in `configs/*.yaml`.
3. **Every generated artifact is reproducible from a `make` target.** Reports are never edited by hand.
4. **Small, typed functions.** Use dataclasses for records. Every CLI goes through `python -m` and has `--help`.
5. **Tests cover the contracts** (canonical schema, extraction, comparison, idempotency), not the libraries.
