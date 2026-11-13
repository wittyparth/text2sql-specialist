# Stage 06: Deduplication (`etl/dedup.py`)

Order matters: run these passes in sequence, and record every removal with a reason.

| Pass | Key | Action | Reason code |
|---|---|---|---|
| 1. Exact | `id` (question + schema + SQL hash) | keep the first by source priority (gretel > sqlcc), then by `source_row_key` | `DUP_EXACT` |
| 2. Same question, same schema, different SQL | `(norm(question), sha(schema_canonical))` | **conflicting labels.** Keep the one with a non-empty result, then the shortest SQL. Drop the others | `DUP_CONFLICTING_LABEL` |
| 3. Same question across sources | `norm(question)` | keep one (gretel preferred) | `DUP_CROSS_SOURCE` |
| 4. **Leakage guard** (runs after split, stage 07) | `norm(question)` and `norm(sql)` present in both train/val and test | remove from **train/val** (never from test) | `LEAKAGE_OVERLAP` |

Measured expectations: about 195 duplicate normalized questions in Gretel, about 326 in sqlcc, and 2 across sources. The leakage guard should find very few, because the split is by domain. **If it finds many, the domain split is broken.**

Not done (documented as a next step): near-duplicate detection with MinHash/embeddings. It's not needed at this scale given the domain split; you can name it as the scale-up path.

## Acceptance
- [ ] The fixture with 3 duplicates and 1 conflicting label yields the expected survivors.
- [ ] The report states "leakage overlap after split: N rows removed". Target ≈ 0.
