"""Small hand-written rows covering each branch of the ETL. No network, no big files."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

PEOPLE_CTX = (
    "CREATE TABLE people (id INT, name VARCHAR(20), age INT);"
    " INSERT INTO people VALUES (1, 'Ann', 30), (2, 'Bob', 41), (3, 'Cy', 25);"
)


def row(
    id=1,
    domain="d0",
    prompt="How many people are older than 26?",
    ctx=PEOPLE_CTX,
    sql="SELECT COUNT(*) FROM people WHERE age > 26;",
    cx="aggregation",
    task="analytics and reporting",
):
    return {
        "id": id,
        "domain": domain,
        "sql_prompt": prompt,
        "sql_context": ctx,
        "sql": sql,
        "sql_complexity": cx,
        "sql_task_type": task,
    }


GOOD = row()
MYSQL_YEAR = row(
    id=2,
    prompt="Which donors gave in 2023?",
    ctx="CREATE TABLE d (donor VARCHAR(10), donation_date DATE);"
    " INSERT INTO d VALUES ('a', '2023-05-01'), ('b', '2022-01-01');",
    sql="SELECT donor FROM d WHERE YEAR(donation_date) = 2023;",
)
# train-file row 5097 of the real dataset: SQLite rejects the ambiguous GROUP BY column
AMBIGUOUS_5097 = row(
    id=5097,
    domain="forestry",
    prompt="What is the total volume of timber sold by each salesperson, sorted by salesperson?",
    ctx=(
        "CREATE TABLE salesperson (salesperson_id INT, name TEXT, region TEXT);"
        " INSERT INTO salesperson (salesperson_id, name, region) VALUES (1, 'John Doe', 'North'),"
        " (2, 'Jane Smith', 'South'); CREATE TABLE timber_sales (sales_id INT, salesperson_id INT,"
        " volume REAL, sale_date DATE); INSERT INTO timber_sales (sales_id, salesperson_id, volume,"
        " sale_date) VALUES (1, 1, 120, '2021-01-01'), (2, 1, 150, '2021-02-01'),"
        " (3, 2, 180, '2021-01-01');"
    ),
    sql="SELECT salesperson_id, name, SUM(volume) as total_volume FROM timber_sales JOIN"
    " salesperson ON timber_sales.salesperson_id = salesperson.salesperson_id"
    " GROUP BY salesperson_id, name ORDER BY total_volume DESC;",
)
MISSING_COLUMN = row(id=3, sql="SELECT height FROM people;")
MISSING_TABLE = row(id=4, sql="SELECT * FROM persons;")
CREATE_SCHEMA_CTX = row(id=5, ctx="CREATE SCHEMA hr; USE hr; " + PEOPLE_CTX)
PUBLIC_QUALIFIED = row(
    id=6,
    ctx="CREATE TABLE public.people (id INT, name TEXT, age INT);"
    " INSERT INTO public.people VALUES (1, 'Ann', 30);",
    sql="SELECT name FROM public.people;",
)
WITH_DELETE = row(
    id=7,
    sql="WITH old AS (SELECT id FROM people WHERE age > 40) "
    "DELETE FROM people WHERE id IN (SELECT id FROM old);",
)
UPDATE_ROW = row(id=8, prompt="Set Ann's age to 31", sql="UPDATE people SET age = 31 WHERE id = 1;")
MULTI_STATEMENT = row(id=9, sql="SELECT 1; SELECT 2;")
BROKEN_CONTEXT = row(id=10, ctx="CREATE TABLE people (id INT, name TEXT; INSERT garbage")
DUPLICATE_KEY_CONTEXT = row(
    id=11,
    ctx="CREATE TABLE t (id INT PRIMARY KEY); INSERT INTO t VALUES (1); INSERT INTO t VALUES (1);",
    sql="SELECT * FROM t;",
)
EMPTY_RESULT = row(
    id=12, prompt="Who is older than 100?", sql="SELECT name FROM people WHERE age > 100;"
)
NO_DATA_CTX = row(
    id=13,
    ctx="CREATE TABLE people (id INT, name VARCHAR(20), age INT);",
    sql="SELECT name FROM people;",
)
RELATIVE_HARDCODED = row(
    id=14,
    prompt="How many people joined in the last 6 months?",
    sql="SELECT COUNT(*) FROM people WHERE id > 0 AND '2022-01-01' < '2023-01-01';",
)
RELATIVE_NOW = row(
    id=15,
    prompt="How many people joined in the last 6 months?",
    sql="SELECT COUNT(*) FROM people WHERE date('now', '-6 months') > '2000-01-01';",
)
RUNAWAY = row(
    id=16,
    sql="WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT max(n) FROM r;",
)


def synthetic_gretel(path: Path, n_domains: int = 20, per_domain: int = 8) -> None:
    """A parquet file shaped like the Gretel one: n_domains x per_domain valid analytics rows."""
    rows = []
    for d in range(n_domains):
        for i in range(per_domain):
            t = f"t_d{d}"
            ctx = f"CREATE TABLE {t} (id INT, v INT, label TEXT);" + "".join(
                f" INSERT INTO {t} VALUES ({k}, {k * (i + 2)}, 'x{k}');" for k in range(5)
            )
            cx = ["basic SQL", "aggregation", "single join", "subqueries"][i % 4]
            sql = [
                f"SELECT label FROM {t} WHERE v > {i}",
                f"SELECT SUM(v) FROM {t} WHERE id < {i % 4 + 2}",
                f"SELECT a.label FROM {t} a JOIN {t} b ON a.id = b.id WHERE a.v > {i}",
                f"SELECT label FROM {t} WHERE v > (SELECT MIN(v) FROM {t}) AND id <> {i % 5}",
            ][i % 4]
            rows.append(
                row(
                    id=d * 1000 + i,
                    domain=f"domain{d:02d}",
                    prompt=f"Question number {i} about topic {d}: list the things",
                    ctx=ctx,
                    sql=sql + ";",
                    cx=cx,
                )
            )
    pq.write_table(pa.Table.from_pylist(rows), path)


def synthetic_sqlcc(path: Path, n: int = 30) -> None:
    rows = [
        {
            "question": f"Which sqlcc items have value above {i}?",
            "context": f"CREATE TABLE table_name_{i} (name VARCHAR, value INT)",
            "answer": f"SELECT name FROM table_name_{i} WHERE value > {i}",
        }
        for i in range(n)
    ]
    path.write_text(json.dumps(rows))
