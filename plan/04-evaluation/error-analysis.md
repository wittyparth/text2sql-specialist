# Error analysis

## Automatic taxonomy (`eval/errors.py`), applied to every wrong prediction
| Class | Rule |
|---|---|
| `EMPTY_OUTPUT` | the extractor returned '' |
| `DIALECT` | error contains `no such function` |
| `SCHEMA_LINK` | `no such column` / `no such table` |
| `AMBIGUOUS` | `ambiguous column name` |
| `SYNTAX` | `syntax error` / `incomplete input` |
| `WRONG_PROJECTION` | executes; the column count differs from the reference |
| `WRONG_ROWCOUNT` | executes; same columns, different row count |
| `WRONG_VALUES` | executes; same shape, different values |
| `WRONG_ORDER` | order_matters item where the multiset matches but the order doesn't |
| `TIMEOUT` | |

The report shows a **base → fine-tuned shift table** per class, e.g. "DIALECT 1 → 0, SCHEMA_LINK 23 → ?". This explains *where* the gain comes from, not just how big it is.

## Manual review (T5.3, about 30 min, done by you)
Read **20 fine-tuned failures** (10 Gretel, 10 Chinook) and label each one:
- `model_error`: genuinely wrong logic
- `gold_noise`: the reference is wrong or the question is ambiguous (synthetic data has some; we saw a "last 6 months" reference with hard-coded dates)
- `metric_strictness`: a correct answer in a different but valid form

Write down the counts plus 3 annotated examples. If `gold_noise` is large, say so. It means the reported execution accuracy is a **lower bound**. Interviewers trust a candidate who audits their own metric.
