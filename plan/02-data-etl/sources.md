# Sources

| | Gretel synthetic_text_to_sql | b-mc2/sql-create-context | Chinook |
|---|---|---|---|
| Format | Parquet (2 files) | JSON (1 file, 78,577 rows) | SQLite database file |
| Access | `hf_hub_download(repo_type="dataset", revision=<pinned sha>)` | same | HTTPS GitHub release asset |
| License | Apache-2.0 | CC-BY-4.0 (attribute in the dataset card) | MIT-style (Chinook project); credit it |
| Rows | 100,000 train + 5,851 test (**both are pooled**, then re-split by domain) | 78,577 | 11 tables |
| Has data? | yes (INSERTs) → result-level validation | **no** (CREATE only) → schema-level validation | yes |
| Role | main training volume + held-out-domain test set | training diversity (short single-table questions, different phrasing) | **eval only** (out-of-distribution, real FK schema) + demo DB |
| Measured quality | 76.3% run as-is, +3.4% repaired, 20.3% unusable | 97.9% run | n/a |

## Why Gretel's own train/test split is NOT used
Its test split shares all 100 domains with train (it's a random row split), so it leaks templates. We pool both files and split by domain ourselves. In the dataset card and README this is stated as a deliberate decision, with the reason.

## Why sql-create-context is capped (≤ 20% of the training mix)
- It comes from WikiSQL and Spider: mostly single-table and short.
- It can't be result-checked.
- Spider-style SQL uses `T1/T2` aliases, which is exactly the pattern behind the base model's Chinook errors (alias mix-ups).

So it adds phrasing diversity, but too much would teach simple and alias-heavy SQL. **Optional ablation** if time allows: train with 0% vs 20% sqlcc.

## Pinning
In `configs/pipeline.yaml`:
```yaml
sources:
  gretel: {repo: gretelai/synthetic_text_to_sql, revision: <commit sha resolved at T1.1>, files: [synthetic_text_to_sql_train.snappy.parquet, synthetic_text_to_sql_test.snappy.parquet]}
  sqlcc:  {repo: b-mc2/sql-create-context, revision: <commit sha>, files: [sql_create_context_v4.json]}
  chinook: {url: https://github.com/lerocha/chinook-database/releases/download/<tag>/Chinook_Sqlite.sqlite, sha256: <computed at T1.1>}
```
Resolve the shas once with `HfApi().dataset_info(repo).sha`. Use the concrete release tag, not `latest`.
