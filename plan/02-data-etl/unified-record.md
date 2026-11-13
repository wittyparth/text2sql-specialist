# Unified record schema (`text2sql.etl.records.Record`)

Every source maps into this one structure. It's also the column set of `records.parquet`.

| Field | Type | Meaning / rule |
|---|---|---|
| `id` | str (16 hex) | `sha256(norm(question) + "\x1f" + schema_canonical + "\x1f" + norm(sql))[:16]`, computed after canonicalization. This is the content identity used for dedup and idempotency |
| `source_row_key` | str | `"{source}:{source_id or row_index}"`, used for incremental processing. Stable across runs |
| `source` | enum | `gretel` · `sqlcc` |
| `source_id` | str \| null | Gretel `id`; sqlcc has none (use the row index) |
| `domain` | str | Gretel `domain`. For sqlcc, `"sqlcc"`, a single pseudo-domain that is train-only |
| `complexity` | str | Gretel `sql_complexity`. For sqlcc, derived from the SQL by the same rules as below |
| `complexity_derived` | str | Always computed from the SQL AST: `basic` / `aggregation` / `single_join` / `multi_join` / `subquery` / `window` / `set_op` / `cte`. Gives one consistent difficulty label across sources |
| `task_type` | str | Gretel `sql_task_type`; sqlcc → `"data retrieval"` |
| `question` | str | stripped; internal whitespace collapsed |
| `context_raw` | str | the source DDL (+ INSERTs) as given |
| `context_sqlite` | str | the context that actually loaded in SQLite (raw or repaired) |
| `schema_canonical` | str | output of `schema.canonicalize()`; this is what the model sees |
| `n_tables` | int | |
| `sql_raw` | str | source SQL |
| `sql` | str | final SQLite SQL (raw or transpiled), one statement, no trailing `;` |
| `repaired` | bool | true if sqlglot transpile was needed for the context or the SQL |
| `repair_dialect` | str \| null | `mysql` / `postgres` |
| `validation_level` | enum | `result` (the tables have rows, so the result was checked) or `schema` (no data; the query parsed and bound to the schema) |
| `result_rows` | int \| null | rows returned (capped at 1000) |
| `result_empty` | bool | |
| `order_matters` | bool | top-level `ORDER BY` present in the reference SQL |
| `time_dependent` | bool | SQL uses `now`/`CURRENT_DATE`/`CURDATE`/`GETDATE`/`NOW()`, or the question is relative ("last N months", "past year", "this year") |
| `n_tokens` | int | Qwen tokenizer: system + user + assistant, rendered with the chat template |
| `status` | enum | `kept` · `dropped` |
| `drop_reason` | enum \| null | see the taxonomy in `stages/03-validate-repair.md`, `05`, `06` |
| `drop_detail` | str \| null | e.g. the SQLite error message |
| `split` | enum \| null | `train` · `val` · `test_heldout` (set by the split stage) |
| `augmented` | bool | distractor tables were added (train only) |
| `run_id` | str | the pipeline run that first produced this record |

`norm(text)`: lowercase, collapse whitespace, strip trailing `;` and punctuation. For SQL, use `sqlglot.parse_one(sql, read="sqlite").sql(normalize=True, pretty=False)` when it parses, otherwise lowercased text with collapsed whitespace.
