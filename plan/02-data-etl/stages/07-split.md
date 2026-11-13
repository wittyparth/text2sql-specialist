# Stage 07: Split by domain (`etl/split.py`)

## Rules
- The Gretel pool (train + test files combined) has **100 domains**.
- `random.Random(seed=42).sample(sorted(domains), 15)` → the first **10 = test_heldout**, the next **5 = val**, the remaining **85 = train**.
- sqlcc (`domain="sqlcc"`) → train only.
- The domain lists are written to the report and the dataset card, so anyone can verify there's no overlap.

## Why domain-level
Gretel rows in one domain share table templates and phrasing patterns. A random row split puts near-twins in train and test, which inflates the score. A domain split tests **generalization to unseen schemas and topics**, which is what a user of the model actually needs.

## Eval-set construction (test_heldout → `data/eval/gretel_heldout_eval.jsonl`)
- Eligible rows: `status=kept`, `validation_level=result`, `result_empty=false`, `time_dependent=false`.
- **Stratified sample of 500** by `complexity_derived`. Use proportional allocation, with a floor of 25 per class where available, so that window/subquery/join classes can be reported separately.
- Every row stores what's needed to rebuild its database (`context_sqlite`) plus `schema_canonical`, `question`, `sql`, `order_matters`, `expected_row_count`, `domain` and `difficulty` (= `complexity_derived`).
- **Frozen:** written once and committed. Later pipeline runs **verify** the file's hash instead of rewriting it, unless you pass `--refreeze-eval`.

## Val set
- 300 rows from the 5 val domains, using the same eligibility rules. Used for eval loss during training, and for a quick sanity check of execution accuracy after training.

## Acceptance
- [ ] `set(train_domains) ∩ set(test_domains) = ∅` (asserted in code).
- [ ] The class counts in the 500 sample are printed in the report.
