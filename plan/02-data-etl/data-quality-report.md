# `reports/data_quality.md`: generated, never hand-edited

Rendered by `etl/report.py` from `reports/data_quality.json`. The app's "Data pipeline" tab reads the same JSON.

## Sections (in order)
1. **Header:** run id, timestamp, git SHA, source revisions + file sha256, sqlglot/pyarrow versions, the config hash.
2. **Funnel per source:** a table with rows `extracted → mapped → in scope (SELECT) → context loaded → executes (raw) → executes (repaired) → passes filters → after dedup → split (train/val/test) → sampled`. Show counts and % of the previous step.
3. **Drop reasons:** a table of code · count · % · and **3 real examples** (question, SQL, SQLite error) per code.
4. **Repair stats:** recovered per dialect (mysql/postgres), plus the top 10 functions or constructs that were rewritten (e.g. `YEAR(` → `strftime`).
5. **Split integrity:** the domain lists per split, the asserted empty intersection, and the number of rows removed by the leakage guard.
6. **Distributions (PNG in `reports/figures/`):**
   - complexity per split (bar)
   - token length histogram, train vs Chinook prompt marked as a vertical line (it shows why augmentation exists)
   - rows per domain
7. **Eval set summary:** gretel_heldout class counts and Chinook difficulty counts.
8. **Stage timings** and the incremental stats (`new`, `skipped`).

## Mini-mockup of section 2
| Stage | Gretel | % prev | sqlcc | % prev |
|---|---|---|---|---|
| extracted | 105,851 | | 78,577 | |
| in scope (SELECT) | ~95k | | 78,577 | |
| executes (raw) | … | | … | |
| + repaired | … | | — | |
| after filters | … | | … | |
| after dedup | … | | … | |
| sampled for training | 8,000 | | 1,500 | |

(The real numbers come from the run. The ~95k is an estimate: 105,851 minus about 10.5k non-SELECT rows.)
