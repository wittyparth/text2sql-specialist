# Stage 09: Sample the training mix + load (`etl/split.py` sampling, `etl/load.py`)

## Training mix (configurable in `configs/pipeline.yaml`)
| Bucket | Target rows | Notes |
|---|---|---|
| Gretel train-domain, kept | 8,000 | stratified by `complexity_derived`: **upweight** joins, subqueries, window and aggregation (the base model's weak classes), cap `basic` at 30% |
| sqlcc, kept | 1,500 | about 16%, under the 20% cap (see sources.md) |
| **Total** | **9,500** | about 35% augmented with distractors |

Why about 10k and not 60k: on a free T4 with Unsloth QLoRA at 1.5B, 10k examples × about 300 tokens average is about 3M tokens. That's an estimated **20–40 minutes for 1 epoch** (confirm from the first 20 steps' throughput; see `03-training/hyperparameters.md`). It leaves time for the eval. More data is a documented scale-up lever.

## Load targets
1. `data/processed/records.parquet`: all records (kept and dropped), zstd-compressed, sorted by id.
2. `data/processed/train.jsonl` and `val.jsonl`, one JSON object per line:
   ```json
   {"messages": [{"role":"system","content":"<SYSTEM_PROMPT>"},
                 {"role":"user","content":"Schema:\n<schema_canonical>\n\nQuestion: <question>"},
                 {"role":"assistant","content":"<sql>"}],
    "meta": {"id":"…","source":"gretel","domain":"…","complexity":"single_join","augmented":false,"repaired":false}}
   ```
   The messages are rendered by `text2sql.prompt.build_messages()`, the same function the eval and the app use.
3. `data/eval/gretel_heldout_eval.jsonl` (frozen; see stage 07).
4. `--push` → `HF_USER/text2sql-sqlite-clean` with configs `train`, `validation`, `test_heldout` and `all_records`, plus the **dataset card** (`etl/load.py` renders it from the report JSON). The card covers: the sources and licenses, the pipeline steps, the funnel numbers, the split method with domain lists, known limitations, and how to reproduce (`make pipeline`).

## Acceptance
- [ ] Every train row's assistant content executes against its own schema. Re-check 200 random rows at load time as a final guard.
- [ ] `train.jsonl` loads with `datasets.load_dataset("json", ...)` and the Qwen chat template renders it.
- [ ] The dataset is visible on the Hub with the card filled in.
