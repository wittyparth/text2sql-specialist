# Metrics and comparison rules (`src/text2sql/sqlexec.py`, `eval/score.py`)

## Primary metric: execution accuracy (EX), normalized
A prediction is correct if, after extraction (`prompt.extract_sql`), it executes in a **read-only** connection to the item's database and its result **equals the reference result** under these rules:

1. **Cell normalization** (applied to both sides):
   - `None` → `None`
   - int/float → `round(float(x), 2)` (money and averages are asked to 2 decimals; `94` == `94.0`)
   - string that parses as a number → same as a number (`'2009'` == `2009`; chinook-086)
   - string matching `YYYY-MM-DD 00:00:00` → `YYYY-MM-DD` (chinook-055)
   - other strings → as-is (case-sensitive; names matter)
2. **Column-order insensitive:** each row becomes a sorted tuple of `repr(normalized cell)`. Measured: the strict compare under-counted the base model, 61.5% vs 62.0%.
3. **Row order:** compared as an ordered list only when the item has `order_matters=true`; otherwise as a multiset (`Counter`).
4. **Same row count** is implied by the multiset/list equality. Extra columns → the rows differ → wrong. Asking for "name and total" but also returning an id counts as wrong. That's intended, because the question specified the output.

## Secondary metrics
| Metric | Definition | Why |
|---|---|---|
| **EX-strict** | no cell normalization, column order respected | shows how much the normalization matters; reported next to EX for transparency |
| **Valid-SQL rate** | prediction executes without error | separates "can't write SQLite" from "wrong logic" |
| **Dialect-error rate** | errors that are `no such function` | directly measures the dialect gain from the repaired training data |
| **Schema-linking error rate** | errors that are `no such column` / `no such table` | the dominant base failure on Chinook (23/23 errors) |
| Latency p50/p95, output tokens | from llama-server timings | cost/speed story |
| Cost per 1k queries | OpenRouter `usage` × price (frontier baseline only); for local runs, state "$0, CPU" | the "why fine-tune a small model" argument |

## Statistics (`score.py`)
- **95% CI** per model: bootstrap with 2,000 resamples over items, percentile method.
- **Paired difference** (fine-tuned − base): paired bootstrap CI of the difference, plus an **exact McNemar test** on the discordant pairs (base right / fine-tuned wrong vs base wrong / fine-tuned right). With n=100 (Chinook) the CIs are wide (about ±9 pts); say so. With n=500 they're about ±4 pts.
- All per-difficulty breakdowns show n next to each percentage. **Never show a % without n.**

## Execution safety (also used by the app)
`run_select(conn, sql, timeout_s=5, max_rows=1000)`:
- Connection opened as `file:…?mode=ro` (URI) for file databases. For rebuilt Gretel databases, it's in memory with an **authorizer** that allows only `SQLITE_SELECT`, `SQLITE_READ`, `SQLITE_FUNCTION`, `SQLITE_RECURSIVE`.
- Progress-handler timeout and `fetchmany(max_rows+1)` to detect truncation.
- Exceptions are returned as data (`ok=False, error_class, message`), never raised to the caller.

## Tests (`tests/test_score.py`, `test_sqlexec.py`)
- column permutation → match; `'2009'` vs `2009` → match; `94` vs `94.0` → match; the datetime suffix → match
- ordered item with swapped rows → mismatch; unordered item with swapped rows → match
- an extra column → mismatch; `DELETE` → blocked by the authorizer; an infinite recursive CTE → timeout
- bootstrap CI of all-correct = [1, 1]; McNemar with no discordant pairs → p = 1
