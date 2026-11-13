# Environment, dependencies, Makefile

## Python
- **Python 3.12** managed by **uv** (`uv python install 3.12`). The system python on this Mac is 3.9, which is too old. Don't use it.
- `pyproject.toml` with optional dependency groups so each container installs only what it needs:

| Group | Packages (pin the exact version at `uv lock` time) | Used by |
|---|---|---|
| core | `pyyaml`, `pydantic>=2` (config models), `rich` (CLI output) | everything |
| etl | `pyarrow`, `huggingface_hub`, `sqlglot`, `datasets` (only for `push_to_hub`), `tokenizers` (token-budget filter with the Qwen tokenizer) | ETL |
| eval | `httpx`, `numpy`, `matplotlib` | eval + report figures |
| app | `gradio`, `httpx`, `pandas` | app |
| dev | `pytest`, `ruff` | tests + CI |

Training dependencies (`unsloth`, `trl`, `peft`, `bitsandbytes`, `wandb`) live **only in the Colab notebook**. They need CUDA and must not pollute the local environment.

## Secrets (`.env`, gitignored; `.env.example` committed)
| Var | Needed for | Required? |
|---|---|---|
| `HF_TOKEN` (write) | pushing the dataset/model, Space deploy | only to publish |
| `WANDB_API_KEY` | training logs (set in Colab secrets, not locally) | training |
| `OPENROUTER_API_KEY` | optional frontier-model baseline in eval | optional |

**Nothing in `docker compose up` needs a secret.** The reviewer runs it with zero setup.

## Makefile targets (the human interface)

| Target | What it does | Proof it worked |
|---|---|---|
| `make setup` | `uv sync --all-groups` | `uv run python -c "import text2sql"` |
| `make test` | `ruff check` + `pytest -q` | all green |
| `make pipeline` | full ETL → `data/processed/*` + `reports/data_quality.{md,json}` | report shows the funnel; **second run prints "0 new records"** |
| `make pipeline-demo-incremental` | run with `--limit 50000`, then full; shows only the new rows being processed | the log line `new=…, skipped=…` |
| `make push-dataset` | push the processed dataset to `HF_USER/text2sql-sqlite-clean` with the dataset card | Hub URL |
| `make serve-native` | Mac fast path: two `llama-server` processes on Metal (8081 base, 8082 fine-tuned) | `curl :8081/health` |
| `make eval MODEL=base SET=chinook` | one eval run → `runs/<id>/` | predictions.jsonl + summary.json |
| `make eval-all` | base + ft × {F16, Q8_0, Q4_K_M} × {gretel_heldout, chinook} (+ OpenRouter if a key is set) | `reports/eval_results.md` |
| `make app` | run Gradio locally against `LLM_BASE_URL`/`LLM_FT_URL` | http://localhost:7860 |
| `make up` / `make down` | `docker compose up -d` / `down` | http://localhost:7860 |
| `make space-build` | build `docker/space.Dockerfile` locally and run it on port 7860 with `--cpus 2` | the same UI, CPU-only |

## Conventions
- `ruff` with default rules plus import sorting, line length 100.
- Logging goes through `rich` / `logging`. No bare prints in library code.
- Every CLI writes a machine-readable JSON next to its human-readable output. Reports are built from the JSON.
