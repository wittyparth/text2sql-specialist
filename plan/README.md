# Text-to-SQL Specialist — Build Plan

> One pipeline that runs end to end: **raw multi-source data → ETL → training dataset → QLoRA fine-tune of a small open-weight model → execution-based evaluation → a Dockerized, CPU-only live demo.**

This folder is the source of truth for *what* we build, *why*, and *how we know it works*.
Every number in here was measured on 2026-11-13, not guessed. See [`00-context/verified-facts.md`](00-context/verified-facts.md).

## The one-paragraph pitch (for the reviewer)

Public text-to-SQL data is noisier than it looks. When I ran every query in `gretelai/synthetic_text_to_sql` (100k rows), **23.7% failed to execute in SQLite**: broken schemas, missing columns, MySQL/Postgres-only functions. I built an idempotent, incremental ETL pipeline. It pulls three sources (Parquet, JSON and a live SQLite database), maps them to one record format, translates dialects with `sqlglot`, **validates every row by running it**, deduplicates, and splits by *domain* to prevent leakage. I then QLoRA-fine-tuned Qwen2.5-Coder-1.5B on a free T4. I measured base vs fine-tuned **execution accuracy** on domains it never saw and on a real 11-table database. The model runs on CPU via llama.cpp in Docker, and a side-by-side demo lets you check the claim yourself.

## How to read this plan

| Folder | What it answers |
|---|---|
| [`00-context/`](00-context/) | Goals, success criteria, every decision with its evidence, measured facts |
| [`01-repo-and-environment/`](01-repo-and-environment/) | Repo tree (every file and its purpose), Python env, Makefile, Docker |
| [`02-data-etl/`](02-data-etl/) | The pipeline: sources, unified record, each stage's contract, quality report, tests |
| [`03-training/`](03-training/) | Prompt format (shared contract), Colab notebook cell by cell, hyperparameters, tracking, export |
| [`04-evaluation/`](04-evaluation/) | Metrics, harness design, eval sets, statistics, error analysis, results template |
| [`05-serving-and-app/`](05-serving-and-app/) | Serving architecture, the website spec, SQL safety, HF Space deploy |
| [`06-deliverables/`](06-deliverables/) | README outline, submission checklist, interview talking points |
| [`07-execution/`](07-execution/) | Timeline with gates, task board with acceptance criteria, risks and fallbacks |

## Definition of done (what the reviewer receives)

1. **GitHub repo** with a README whose first screen shows the results table and the live demo link.
2. **Live demo**: an HF Space on CPU. If free Docker Spaces need PRO, use PRO or a Cloudflare tunnel to the Mac (decision D12, task T6.0). It shows base vs fine-tuned side by side, runs the SQL and shows the results.
3. **`docker compose up`** runs the same demo on any Mac/Linux machine. No GPU and no API keys needed.
4. **Dataset on the HF Hub** with a dataset card, and the **model on the HF Hub** (LoRA adapter + GGUF) with a model card.
5. **Public W&B run** with the training and validation loss curves.
6. **Reproducible ETL**: `make pipeline` regenerates the dataset and `reports/data_quality.md` from scratch; a second run is a no-op.
7. **Eval report** `reports/eval_results.md`: base vs fine-tuned (vs Q8/Q4 quantization, vs an optional frontier API), with 95% CIs, per-difficulty breakdown and error analysis.

## Scope decisions in one place

- **In:** SELECT-only analytics questions over SQLite. Three data sources. SFT with QLoRA. Execution-accuracy eval. CPU serving. Docker. HF Space.
- **Out (documented as next steps):** DPO round (design written in `03-training/next-steps-dpo.md`), multi-turn or clarifying questions, write queries (INSERT/UPDATE), other SQL dialects, GPU serving.
