# Stage 04: Canonical schema serialization (`text2sql/schema.py`, shared with eval and app)

## Why (measured)
- Raw schemas vary by source and dialect. Chinook's raw DDL is 4,138 characters.
- The model must see **one consistent format** in training, eval and the live app; otherwise we'd be measuring format shift, not skill.

## Function contract
```python
def canonicalize(conn: sqlite3.Connection, sample_rows: int = 2, max_value_chars: int = 30) -> str
```
- Tables come from `sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'`, **sorted by name**.
- One line per table:
  `CREATE TABLE {name} ({col} {TYPE}[ PRIMARY KEY][ REFERENCES {t}({c})], ...);`
  - TYPE comes from `PRAGMA table_info`. An empty type is written as `TEXT`.
  - Foreign keys come from `PRAGMA foreign_key_list`. These are critical: the base model's Chinook errors were wrong join paths.
  - Identifiers that need quoting (spaces, keywords) are wrapped in double quotes.
- Then up to `sample_rows` rows: `-- v1, v2, …`. NULL is written as `NULL`; values are cut to 30 characters.
- Views are listed as `-- VIEW {name}` (no body).
- The output is deterministic: same database → byte-identical string. Covered by a test.

## Measured size
- Gretel p99: 771 characters for prompt + schema + SQL.
- Chinook: 3,375 characters, **1,339 tokens** in the full prompt.
- This size gap is why stage 08 (distractor augmentation) exists.

## Acceptance
- [ ] Deterministic (hash-equal across two calls and two processes).
- [ ] Round trip: `executescript(canonicalize(...) DDL lines)` recreates the tables. Comment lines are ignored.
- [ ] Chinook output matches the golden file `tests/golden/chinook_canonical.txt`.
