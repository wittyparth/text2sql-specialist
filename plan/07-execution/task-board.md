# Task board (tick as you go; each task has a check you can see)

## T0: Scaffold
- [x] T0.1 `git init`, `.gitignore`, `.env.example`, LICENSE · ✔ `git status` clean after the first commit
- [x] T0.2 `pyproject.toml` with dependency groups, `uv lock`, Makefile skeleton · ✔ `make setup` works
- [x] T0.3 `prompt.py`, `schema.py`, `sqlexec.py` + tests (incl. the Chinook golden file) · ✔ `make test` green
- [x] T0.4 move `data/eval/chinook_eval.jsonl` + validator under the repo conventions; copy `chinook.sqlite` to `data/demo/` · ✔ validator 100/100

## T1: ETL
- [x] T1.1 resolve and pin the source revisions + Chinook tag/sha256 in `configs/pipeline.yaml` · ✔ `pipeline status` shows the revisions
- [x] T1.2 extract + manifest + retries + atomic writes · ✔ the second run downloads 0
- [x] T1.3 mappers + Record · ✔ unique keys asserted
- [x] T1.4 validate + repair + taxonomy · ✔ fixture tests; full run under 60 s; id 5097 → `SQL_AMBIGUOUS`
- [x] T1.5 canonicalize in the pipeline · ✔ deterministic
- [x] T1.6 filters (incl. time-dependence, token budget with the Qwen tokenizer) · ✔ fixture tests
- [x] T1.7 dedup + leakage guard · ✔ fixture tests
- [x] T1.8 domain split + frozen eval sample (500) + val (300) · ✔ empty intersection asserted
- [x] T1.9 distractor augmentation · ✔ 100% of augmented rows re-execute with the same row count
- [x] T1.10 sampling + load (Parquet, JSONL, eval JSONL) · ✔ train.jsonl renders with the Qwen template
- [x] T1.11 report (md + json + figures) · ✔ funnel within 2 pts of verified-facts
- [x] T1.12 idempotency + incremental tests; `pipeline-demo-incremental` · ✔ `new=0` on rerun
- [x] T1.13 dataset card + `--push` · ✔ on the Hub
- [x] T1.14 `build_demo_dbs.py` for 3 held-out domains · ✔ 3 `.sqlite` files in `data/demo/`

## T2: Training (agent writes the notebook; you run it on Colab)
- [x] T2.1 cells 0–6 · ✔ rendered example looks right
- [x] T2.2 cells 7–10 · ✔ masking verified, throughput projection noted
- [ ] T2.3 cell 11 train · ✔ public W&B run, eval loss doesn't rise
- [x] T2.4 cell 12 quick val execution accuracy · ✔ fine-tuned > base (G3)
- [x] T2.5 cells 13–15 push the adapter + GGUF · ✔ `llama-server -hf` works on the Mac

## T3: Eval
- [ ] T3.0 human spot-check of 20 Chinook items, then freeze · ✔ sha256 recorded in eval.yaml
- [x] T3.1 client/run/score/errors/compare + tests · ✔ `make test`
- [ ] T3.2 base runs on both sets (Q4, F16) · ✔ Chinook = 59% one request at a time (matches the probe)
- [ ] T3.3 fine-tuned runs (Q4, Q8, F16) · ✔ summaries written
- [ ] T3.4 optional frontier run via OpenRouter · ✔ cost/latency row
- [ ] T3.5 `eval_results.md` + figures · ✔ generated
- [ ] T3.6 manual audit of 20 failures · ✔ counts in the report

## T4: App + Docker
- [x] T4.1 Gradio app, all 4 tabs · ✔ the acceptance list in app-spec.md
- [ ] T4.2 `app.Dockerfile` + compose · ✔ `docker compose up` on a clean clone
- [x] T4.3 warmup · ✔ warm Chinook under 3 s on Mac Docker
- [x] T4.4 `run.sh` + `ollama/*.Modelfile` · ✔ acceptance list in local-run.md (Ollama mode and Docker-only mode)

## T5–T6: Space
- [ ] T6.0 **do this early (during T0, 2 min):** can your HF account create a free Docker Space? · ✔ decides between Space, PRO or tunnel (hf-space.md)
- [ ] T6.1 `space.Dockerfile` + entrypoint · ✔ `docker run --cpus 2` works locally
- [ ] T6.2 `deploy_space.py`, deploy · ✔ public Space works; latency measured

## T7: Ship
- [ ] T7.1 README (sections 1/4/7 by you) · T7.2 CI green · T7.3 submission checklist · T7.4 send
