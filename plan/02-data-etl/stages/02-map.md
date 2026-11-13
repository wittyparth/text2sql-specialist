# Stage 02: Map to the unified record (`etl/mappers.py`)

**Input:** raw rows. **Output:** partial `Record`s (no validation fields yet).

| Record field | Gretel | sql-create-context |
|---|---|---|
| question | `sql_prompt` | `question` |
| context_raw | `sql_context` | `context` |
| sql_raw | `sql` | `answer` |
| domain | `domain` | `"sqlcc"` |
| complexity | `sql_complexity` | derived |
| task_type | `sql_task_type` | `"data retrieval"` |
| source_id | `str(id)` | `None` → key uses the row index |

## Normalization done here (cheap, text-only)
- Question: strip, collapse whitespace, fix doubled spaces before `?`. **Don't** lowercase; case carries meaning (names).
- SQL: strip, remove trailing `;`, collapse runs of whitespace (outside string literals; use the sqlglot tokenizer, not a regex).
- Context: strip, ensure statements end with `;`.

## Schema-mapping edge cases
- A Gretel `id` collides across the pooled train and test files (they're independent id spaces). The key is therefore `gretel:{file}:{id}`.
- sqlcc questions sometimes end with ` ?` (space before the question mark), which gets normalized.
- Empty or whitespace-only fields → `drop_reason=EMPTY_FIELD`.

## Acceptance
- [ ] 100% of rows map (no exceptions). The count per source is logged.
- [ ] The `source_row_key` is unique across all rows. Assert it.
