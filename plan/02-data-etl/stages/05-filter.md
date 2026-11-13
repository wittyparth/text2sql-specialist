# Stage 05: Quality and scope filters (`etl/filters.py`)

| Rule | Drop reason | Why |
|---|---|---|
| question < 10 or > 500 chars | `QUESTION_LENGTH` | garbage or prompt-stuffing |
| SQL > 2,000 chars | `SQL_LENGTH` | outlier, not learnable at 1.5B |
| full rendered chat (Qwen tokenizer + chat template) > **1,800 tokens** | `TOKEN_BUDGET` | `max_length=2048` in training, with margin for distractors |
| `time_dependent` **and** the question is relative ("last 6 months") **and** the SQL has hard-coded dates (no now-function) | `TIME_RELATIVE_HARDCODED` | the reference answer contradicts the question. It would teach the model to invent dates. Seen in the base-model probe: "last 6 months" → `'2022-01-01'` |
| `time_dependent` with a now-function (after the transpile it's `date('now', '-6 months')`) | **kept for training**, excluded from eval | correct SQLite idiom to learn; but its result changes over time, so it can't be a stable eval item |
| `result_empty` | **kept for training**, excluded from eval | the SQL is valid and teaches syntax. But an empty reference makes two different wrong answers "match" in execution accuracy (both return nothing) |
| `task_type` not in {analytics and reporting, data retrieval} | already dropped as `NOT_SELECT` in stage 03 | scope |

Relative-time detection (question): regex `\b(last|past|previous|recent|this|current)\s+(\d+\s+)?(day|week|month|quarter|year)s?\b|\b(today|yesterday|ytd)\b`, case-insensitive.
Now-functions (SQL): `now\(|current_date|current_timestamp|curdate|getdate|sysdate|date\('now'`.

## Acceptance
- [ ] Each rule has a fixture test.
- [ ] The report lists counts and 3 examples per rule.
