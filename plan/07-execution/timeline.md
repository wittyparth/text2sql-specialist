# Timeline with gates (T+0 = when we start building)

**Critical path:** ETL → dataset on Hub → Colab training + export → eval → app with fine-tuned model → Space → README.
**Parallel work:** the app, Docker and eval harness are built **against the base model** while training runs. The `llm-ft` service temporarily points at the base GGUF and gets switched once the fine-tuned GGUF exists.

| Time | Claude (in this repo) | You | Gate (must be true to continue) |
|---|---|---|---|
| **T+0:00–0:20** | scaffold: pyproject, uv lock, Makefile, configs, `prompt.py`, `schema.py`, `sqlexec.py` + their tests | create a HF write token, W&B account; open Colab on a T4 and run cells 0–2 | — |
| **T+0:20–1:40** | ETL stages 01–09 + report + idempotency test | review `stages/*.md` while I build; read 20 Chinook items (the human spot-check) | — |
| **T+1:40–2:00** | run the full pipeline; compare numbers with `verified-facts.md` | read `reports/data_quality.md`; ask anything you can't explain | **G1:** tests green; funnel within 2 pts of profiling; domain intersection empty; a second run gives `new=0`; dataset pushed to the Hub |
| **T+2:00–3:15** | eval harness (`client`, `run`, `score`, `compare`, `errors`); run the **base** model on both frozen sets | read the generated notebook; run cells 0–10, including the **throughput probe** | **G2:** masking verified (cell 9 prints exactly the SQL); projected train time ≤ 45 min |
| **T+3:15–4:15** | Gradio app + `docker-compose.yml` + `app.Dockerfile` (using the base model in both columns for now) | cell 11: **train** (watch W&B); cell 12 quick val execution accuracy | **G3:** fine-tuned val execution accuracy > base on the same 300 items. If not → see the decision rules below |
| **T+4:15–4:45** | `space.Dockerfile` + entrypoint + warmup; local `--cpus 2` test | cells 13–14: push the adapter + GGUF (Q4/Q8/F16) | GGUF on the Hub; `llama-server -hf <repo>:Q4_K_M` answers correctly |
| **T+4:45–5:30** | `make eval-all` (base/fine-tuned × Q4/Q8/F16 × 2 sets, + frontier if a key is set); `compare.py` → `eval_results.md` | manual audit of 20 failures (error-analysis.md) | **G4:** results report generated; numbers are believable (spot-check 5 wins by hand) |
| **T+5:30–6:30** | switch `llm-ft` to the real GGUF; `docker compose up` on a clean clone; deploy the Space; measure Space latency | test the Space on your phone and in an incognito window | **G5:** Space live, warm request under 4 s, or the fallback applied |
| **T+6:30–7:30** | generate README tables/figures; repo tidy; CI green | **write README sections 1, 4 and 7 in your own words**; record a 20 s GIF | — |
| **T+7:30–8:00** | submission checklist pass | send the message (talking-points.md) | **G6:** every checklist box ticked |

**Total about 8 h.** That leaves about 1–2 h of buffer in your 10, which is what Colab disconnects and the Space build will use up.

## Decision rules at gates
- **G1 numbers are off by more than 2 pts:** stop and find out why. A silent ETL bug poisons everything downstream.
- **G2 projection is over 45 min:** cut `max_steps`, don't cut eval time.
- **G3 fine-tuned ≤ base:**
  1. check the chat template and system prompt in the rendered training text
  2. check masking
  3. check that the LR isn't too high (the loss curve is spiky)
  4. if those are all fine → ship anyway and report it honestly, with the error-class shift. **Never hide a negative result.**
- **Fine-tuned better on Gretel but worse on Chinook:** report it as overfitting to synthetic short schemas. This is exactly what distractor augmentation targets; propose the ablation as a next step.
- **Running late:** cut in this order: frontier baseline → Q8 eval → Space (keep Docker) → incremental demo target. **Never cut:** base-vs-fine-tuned eval on both sets, the data-quality report, `docker compose up`.
