# Stage 08: Distractor-table augmentation (train only) (`etl/augment.py`)

## Problem (measured)
- Training prompts: p50 is about 120 tokens, with 1–3 tables.
- Chinook prompt: **1,339 tokens, 11 tables.**
- The base model's Chinook errors were **all `no such column`**: alias mix-ups and invented join paths, i.e. a failure to pick the right tables and columns in a big schema (*schema linking*).
- If we fine-tune only on tiny schemas, the model may get *worse* on large ones. That's risk R7.

## Technique
For a seeded random **35%** of train records (Gretel and sqlcc):
1. Draw **k ~ Uniform{3..8}** distractor tables from *other train records* (never from val or test domains, to avoid leakage). Skip any whose name collides with an existing table.
2. Build the merged database: original context + distractor DDL and sample rows → `canonicalize()`. Tables end up sorted by name, so the distractors are interleaved, not appended at the end.
3. **Re-execute the reference SQL on the merged database** and require the same result row count. The augmentation is provably label-preserving.
4. Check the token budget again (≤ 1,800). If it's over, reduce k.
5. Set `augmented=true` and keep the original id plus the suffix `-aug`. The un-augmented original is **not** also kept, so we don't double-count.

## Target distribution after augmentation
About 35% of training prompts fall in the 500–1,500 token range, which covers Chinook-size schemas. Plot the histogram in the report.

## Honest framing (for the README)
This is a standard robustness technique: it trains schema linking under noise. It doesn't add new questions. Its effect is measured on Chinook (out of distribution). **Optional ablation** if there's time: train once without augmentation and compare Chinook execution accuracy.

## Acceptance
- [ ] 100% of augmented rows re-execute with the same row count. Rows that fail are dropped with `AUG_FAILED`.
- [ ] No distractor table comes from a val or test domain (assert).
