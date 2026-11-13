# CLAUDE.md: how to build this project (read fully before writing any code)

You are building **Text-to-SQL Specialist**:

> multi-source **ETL** → validated training dataset → **QLoRA fine-tune** of Qwen2.5-Coder-1.5B → **execution-based evaluation** → a CPU-only demo that runs locally in one step (`./run.sh` / `docker compose up`)

The owner is preparing this as proof of skill for an Applied AI role (fine-tuning + ETL). It will be **read by a reviewer** and **defended in an interview**. Build it the way a senior engineer would: correct, measured, reproducible, small, and honest.

The detailed spec lives in `plan/`. This file tells you **how to work**; `plan/` tells you **what to build**. If they conflict, `plan/00-context/decisions.md` wins. If a decision turns out wrong, don't silently deviate: update the decision with the new evidence, then build.

---

## 0. Read first, in this order
1. `plan/README.md`: goal, definition of done, scope
2. `plan/00-context/verified-facts.md`: **numbers measured on real data/tools. Your implementation must reproduce them** (± 2 pts) or you must explain why not
3. `plan/00-context/decisions.md`: D1–D14, with evidence
4. `plan/07-execution/timeline.md` + `task-board.md` + `risks.md`: order, gates, cut rules
5. Then the spec for the phase you're in (table below)

## 1. Phases, specs and done-gates

| Phase | Spec files | Done when (all must hold; show the evidence) |
|---|---|---|
| **T0 Scaffold** | `plan/01-repo-and-environment/*`, `plan/03-training/prompt-contract.md`, `plan/02-data-etl/stages/04-canonicalize.md`, `plan/04-evaluation/metrics.md` | `make setup && make test` green; `prompt.py`, `schema.py`, `sqlexec.py` have tests incl. the Chinook golden file; `data/eval/validate_chinook_eval.py` passes 100/100 |
| **T1 ETL** | `plan/02-data-etl/README.md`, `sources.md`, `unified-record.md`, `stages/01…09`, `data-quality-report.md`, `tests.md` | Gate **G1** in timeline.md: funnel within 2 pts of verified-facts; domain intersection empty (asserted); 2nd run `new=0` with byte-identical outputs; `reports/data_quality.md` generated; id 5097 → `SQL_AMBIGUOUS`; dataset pushed (needs `HF_TOKEN`; ask the owner) |
| **T2 Training** | `plan/03-training/*` | You **write** `notebooks/train_qlora_colab.ipynb` exactly to `colab-notebook.md`. **The owner runs it on Colab** (you have no GPU). Done when the owner reports G2/G3 numbers and the GGUF is on the Hub |
| **T3 Eval** | `plan/04-evaluation/*` | Base Q4 on Chinook, one request at a time, reproduces **59%** (the deterministic prototype result; ±1 allowed for a different llama.cpp build) as a sanity check of your harness; full matrix → `reports/eval_results.md` generated; tests for every comparison rule |
| **T4 App + local run** | `plan/05-serving-and-app/architecture.md`, `app-spec.md`, `local-run.md`, `plan/01-repo-and-environment/docker.md` | the acceptance lists in app-spec.md and local-run.md pass; `./run.sh` works in Ollama mode **and** Docker-only mode; a clean clone + `docker compose up` works with no `.env` |
| **T6 Hosting** | `plan/05-serving-and-app/hf-space.md` | the owner has done check T6.0; the chosen path (Space / PRO / tunnel) is live and its latency is measured |
| **T7 Ship** | `plan/06-deliverables/*` | the submission checklist is fully ticked; README numbers are copied from the generated reports |

Prototypes that already work (reuse their logic, don't rediscover it): `scripts/prototypes/` (`check.py` validation, `profile.py` full profiling + sqlglot repair, `canon.py` canonical schema, `base_probe.py` / `chinook_probe.py` eval loop).

---

## 2. How to work (non-negotiable engineering behaviour)

**Verify, don't assume.**
- Before using any library API, check the installed version's docs (context7 or `--help`). Unsloth, TRL, Gradio, Ollama and llama.cpp change fast. `verified-facts.md` lists what has already been checked.
- After building each stage, **run it on real data and compare with the expected numbers**. A mismatch is a bug until proven otherwise.

**Small vertical slices.** Get one thing working end to end before widening it. Example: extract → map → validate on 1,000 rows → report, *then* all stages, *then* the full data.

**Tests for contracts, written alongside the code.**
- Every rule in the specs that has a ✔/acceptance line gets a test.
- Use fixtures; no network in unit tests.
- Keep tests fast (whole suite under 30 s).

**Determinism and reproducibility.**
- Seeds come from config. Sort outputs.
- Pin source revisions and the Docker image digest.
- Record versions and the git SHA in every report.

**Fail loudly in pipelines, gracefully in the app.**
- ETL: assertions on invariants (unique keys, empty split intersection, augmented rows re-execute), so a broken invariant stops the run.
- App: every model or SQL error becomes a readable message in the UI. Never show a stack trace.

**Never fabricate or hand-edit results.**
- Reports and README tables come from generated JSON.
- If a number is bad (fine-tuned ≤ base, Chinook regression), report it with analysis. Hiding it is the worst possible outcome for this project.

**Keep scope.** SELECT-only SQLite, single turn. Don't add features outside `plan/` without listing them under "Good to add" (section 4) and getting the owner's go-ahead. Gold-plating costs the deadline.

**Ask the owner only for what is truly theirs:** tokens/accounts (HF, W&B, OpenRouter), running Colab, paid-hosting choices, writing README sections 1/4/7 in their own voice, and the human spot-checks (20 Chinook items, 20 failure audits). Decide everything else yourself, using the plan.

**Secrets:** read from `.env` and never print them. `.env` stays gitignored. Grep the git history before shipping.

### Code standards
- Python 3.12, `uv`, `src/` layout, type hints on public functions, dataclasses or pydantic for records and config.
- `ruff` clean, functions under about 40 lines, no dead code, no commented-out code.
- One shared contract: `prompt.py`, `schema.py` and `sqlexec.py` are imported everywhere and **never** duplicated.
- CLIs run via `python -m`, have `--help`, and write machine-readable JSON next to human-readable output.
- Comments explain *why*, not *what*. Match the density of the surrounding code.

---

## 3. Edge cases you must handle and test

**Data / ETL**
- Context loads only after removing `CREATE SCHEMA` / `USE` / `public.` qualifiers. MySQL `AUTO_INCREMENT`, `ENUM`, `SERIAL`.
- SQL with MySQL/Postgres functions (`YEAR`, `DATE_SUB`, `NOW`, `TO_CHAR`, `ILIKE`). sqlglot "unsupported" warnings count as a failed repair.
- `WITH … UPDATE/DELETE/INSERT` (all of Gretel's "CTEs" rows) → `NOT_SELECT`. Multi-statement SQL. A trailing `;`.
- An infinite recursive CTE / a giant cross join → `TIMEOUT` within about 2 s, never a hang.
- `UNIQUE constraint failed` while loading INSERTs. Empty tables (sqlcc → `validation_level=schema`).
- Identifiers with spaces or keywords (quote them in the canonical schema). Non-ASCII values (Chinook has `Luís`, `Gonçalves`).
- Duplicates: exact, conflicting labels, cross-source. Leakage across splits. Relative-time questions with hard-coded dates.
- Gretel `id` collisions between the train and test files (keys include the file name).
- A partial download / corrupted `.part` file. A re-run after a crash mid-stage (atomic writes).

**Model output / eval**
- Empty output, prose before the SQL, fenced output, `SQL:` prefix, multiple statements, a missing `FROM`, output that never stops (cap `max_tokens`, stop at `<|im_end|>`).
- A prediction that is a write query → blocked by the authorizer, counted as wrong, never executed.
- Results: column permutation, numeric strings vs numbers, `94` vs `94.0`, datetime vs date, NULLs, ordered vs unordered, extra columns, >1000 rows (truncation flag), floating-point noise.
- **Determinism:** evals run one request at a time. Parallel batching flips about 5% of greedy outputs (measured), so never compare runs with different concurrency.
- Endpoint failures: timeout, 500 (context overflow), connection refused → retry with backoff (3×), then record as `ENDPOINT_ERROR`. **Never silently score it as wrong SQL.**
- The frozen eval file changed → refuse to run (sha256 check against `configs/eval.yaml`).

**App / serving**
- A backend down (one column shows "unavailable", the other still works). Cold start (warming banner). Two users at once (queue).
- Custom schema containing `DROP`/`ATTACH`/`PRAGMA` → rejected. A 20 KB+ schema → rejected. A schema that fails to load → clear message.
- Ollama with a 4,096 default context → Modelfile `num_ctx 8192`. A Docker-on-Mac user expecting GPU speed → the README explains CPU-only.
- Port 7860 already in use → `run.sh` prints the conflict and exits cleanly.

---

## 4. Things commonly missed (check before declaring done)
- [ ] The **prompt/format parity** test: the training JSONL's user message for a record is byte-identical to what `build_messages` produces in the app for the same schema and question.
- [ ] The **metric parity**: the app's "matches reference" badge uses the same `results_match` as the eval.
- [ ] The base-model numbers are re-measured with the final harness (not the prototype's) before the comparison.
- [ ] Every percentage in a report has its **n** next to it. The CIs are present.
- [ ] The dataset card and model cards cite the sources and their licenses (Apache-2.0, CC-BY-4.0, Chinook).
- [ ] `docker compose up` was tested from a **fresh clone in a new directory**, not the working copy.
- [ ] The README states CPU-only latency honestly (the Space or Docker number, not the Metal number).
- [ ] The notebook is committed **with outputs** (proof the training ran).
- [ ] CI is green on GitHub, not just locally.

### Good to add, only after all gates pass, in this priority order
1. A frontier-model row via OpenRouter (cost/latency/accuracy comparison). Already designed.
2. An ablation: with vs without distractor augmentation (Chinook execution accuracy).
3. A `make doctor` target: checks Docker/Ollama/uv versions, ports and model availability, then prints fixes.
4. A pre-commit hook (ruff + pytest on the changed modules).
5. A one-page architecture diagram (PNG) for the README and the About tab.

Not to add today: DPO training, multi-turn, other SQL dialects, a GPU serving path. These are documented as next steps instead.

---

## 5. Self-review before marking any task done
1. Run it again from a clean state. Same result?
2. Read the diff as the reviewer would: anything unclear, duplicated, unused or over-engineered? Remove it.
3. Tests cover the acceptance lines of the spec you implemented?
4. Numbers match `verified-facts.md`, or the difference is explained in the report?
5. Tick the box in `plan/07-execution/task-board.md`.

## 6. How to report progress to the owner
Short and factual, after each phase:
- **Done:** what now works, and the command that shows it.
- **Evidence:** the key numbers or output lines (copied, not paraphrased).
- **Deviations:** anything that differs from `plan/`, and why. If it matters, update `decisions.md`.
- **Needs you:** only the owner-only items (tokens, Colab run, spot-checks, hosting choice).
- **Next:** the next task ID.
