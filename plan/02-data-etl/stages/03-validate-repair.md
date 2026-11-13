# Stage 03: Validate by execution + repair (`etl/validate.py`)

This is the heart of the ETL story: **every training example is proven to run in SQLite.**

## Algorithm per record
```
1. scope check (before executing anything):
     parse sql_raw with sqlglot (read=sqlite, fallback mysql)
     top-level statement must be SELECT / UNION / INTERSECT / EXCEPT / WITH…SELECT
     else → drop NOT_SELECT                        (catches all 273 Gretel "CTEs" rows: they are WITH…UPDATE/DELETE/INSERT)
     multiple statements → drop MULTI_STATEMENT

2. load context into fresh in-memory SQLite (progress-handler timeout 2 s):
     a) pre-clean: remove statements starting with CREATE SCHEMA / USE / SET / CREATE DATABASE;
                   strip schema qualifiers like `public.` / `schemas.`   (fixes "unknown database public")
     b) executescript(context)                       → ok → context_sqlite = cleaned context
     c) on error: transpile each statement mysql→sqlite (then postgres→sqlite), retry
     d) still failing → drop CTX_LOAD_FAILED (detail = sqlite error)

3. execute SQL (timeout 2 s, fetchmany 1000):
     a) raw SQL                                      → ok
     b) on error: sqlglot.transpile(sql, read="mysql", write="sqlite"), retry; then read="postgres"
        – transpiled output must still be a single SELECT (re-check scope)
        – sqlglot "unsupported" warnings are captured; if the transpile emitted any, treat as failed repair
     c) still failing → drop by error class:
          "no such column" → SQL_NO_SUCH_COLUMN     "no such table" → SQL_NO_SUCH_TABLE
          "no such function" → SQL_NO_SUCH_FUNCTION  "ambiguous column" → SQL_AMBIGUOUS
          "syntax error" → SQL_SYNTAX                 interrupted → TIMEOUT          else → SQL_OTHER

4. record: sql (final), repaired, repair_dialect, result_rows, result_empty,
           validation_level = "result" if any table has ≥1 row else "schema",
           order_matters = top-level ORDER BY in sqlglot AST
```

## Expected numbers (from today's profiling, to sanity-check the implementation)
- Gretel: about 76% run raw and about 3.4% are repaired. NOT_SELECT accounts for about 10.5k rows (data manipulation + definition). Data-manipulation rows that are dropped as NOT_SELECT are no longer counted as "SQL failures", so the reported failure rate among SELECT rows will be **lower** than the 17.5% we measured over all rows. Report both numbers honestly.
- sqlcc: about 97.9% run.
- **If the implementation's numbers differ from these by more than 2 points, investigate before moving on.** It means a bug in either the profiling or the pipeline.

## Why we repair instead of only dropping
Dialect errors (`YEAR()`, `DATE_SUB`, `NOW()`) are exactly the base model's weakness: we saw `YEAR(donation_date)` fail. Repaired rows **teach the SQLite dialect**. The report shows how many rows were recovered per dialect.

## Edge cases
- Contexts that rely on `AUTO_INCREMENT`, `SERIAL`, `ENUM` → transpile handles some of them; the rest are dropped.
- Contexts that create **views**: allowed if they load.
- Very large INSERT blocks: the timeout protects against them.
- `UNIQUE constraint failed` while loading INSERTs (bad synthetic data) → CTX_LOAD_FAILED.
- Floats: results are stored only as row counts. Values are re-derived at eval time.

## Acceptance
- [ ] Unit tests cover each drop reason with a fixture row, plus one repaired-MySQL fixture (`YEAR(d)` → `strftime('%Y', d)` or equivalent that executes).
- [ ] The first test-split row (id 5097, ambiguous `GROUP BY salesperson_id`) ends up as `SQL_AMBIGUOUS`. **It's the README's headline example.**
- [ ] The stage runs over the full data in under 60 s on the M5.
