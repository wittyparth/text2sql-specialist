"""Stages 03 + 04: prove each example runs in SQLite (repairing dialects where possible), then
serialize its schema canonically. Everything here is a pure function of one Record so the stage
can be fanned out over a process pool."""

import logging
import re
import sqlite3
import time
from collections.abc import Iterable
from functools import partial
from multiprocessing import Pool

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, SqlglotError

from ..schema import canonicalize
from ..sqlexec import run_select
from .records import Record, make_id

# sqlglot warns on every statement it can only parse as a raw Command; we judge by execution
logging.getLogger("sqlglot").setLevel(logging.ERROR)

DIALECTS = ("mysql", "postgres")
_SELECT_TYPES = (exp.Select, exp.SetOperation, exp.Subquery)
_NOT_SELECT_WORDS = re.compile(
    r"^\s*(insert|update|delete|create|drop|alter|replace|truncate|pragma|attach)\b", re.I
)
# statement-initial only (after a ';' or at the start), contexts are often written on one line
_DROP_STATEMENTS = re.compile(
    r"(^|;)\s*(?:create\s+schema|create\s+database|use|set)\b[^;]*", re.I | re.S
)
_SCHEMA_QUALIFIER = re.compile(r"\b(?:public|schemas?)\.(?=[A-Za-z_\"`\[])", re.I)
_AGGREGATES = (exp.AggFunc,)


def parse_statements(sql: str) -> list[exp.Expression] | None:
    """Parse as SQLite first, then MySQL (the dialect most of Gretel's odd SQL comes from)."""
    for dialect in ("sqlite", "mysql"):
        try:
            return [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
        except SqlglotError:
            continue
    return None


def scope_error(sql: str) -> tuple[str | None, exp.Expression | None]:
    """NOT_SELECT / MULTI_STATEMENT before anything is executed."""
    stmts = parse_statements(sql)
    if stmts is None:
        # unparseable: let SQLite produce the real error, unless it obviously isn't a SELECT
        return ("NOT_SELECT", None) if _NOT_SELECT_WORDS.match(sql) else (None, None)
    if len(stmts) > 1:
        return "MULTI_STATEMENT", None
    if not stmts or not isinstance(stmts[0], _SELECT_TYPES):
        return "NOT_SELECT", None
    return None, stmts[0]


def derive_complexity(tree: exp.Expression | None) -> str:
    if tree is None:
        return "basic"
    if tree.args.get("with_") or tree.args.get("with") or tree.find(exp.With):
        return "cte"
    if isinstance(tree, exp.SetOperation):
        return "set_op"
    if tree.find(exp.Window):
        return "window"
    inner = [s for s in tree.find_all(exp.Select) if s is not tree]
    if inner:
        return "subquery"
    joins = len(list(tree.find_all(exp.Join)))
    if joins >= 2:
        return "multi_join"
    if joins == 1:
        return "single_join"
    if tree.args.get("group") or tree.find(*_AGGREGATES):
        return "aggregation"
    return "basic"


def has_order_by(tree: exp.Expression | None) -> bool:
    if tree is None:
        return False
    if isinstance(tree, exp.Subquery):
        tree = tree.this
    return tree.args.get("order") is not None


def pre_clean(ctx: str) -> str:
    """Drop statements SQLite has no equivalent for and strip schema qualifiers like 'public.'."""
    return _SCHEMA_QUALIFIER.sub("", _DROP_STATEMENTS.sub(r"\1", ctx))


# SQLite date modifiers know days/months/years but not weeks: '-1 WEEK' silently gives NULL
_WEEK_MODIFIER = re.compile(r"'([+-]?)(\d+)\s+weeks?'", re.I)
_LEFTOVER_INTERVAL = re.compile(r"\bINTERVAL\s+'?\d", re.I)

_DATE_PARTS = ((exp.Year, "%Y"), (exp.Month, "%m"), (exp.Day, "%d"))


def _fix_date_parts(tree: exp.Expression) -> exp.Expression:
    """sqlglot leaves YEAR()/MONTH()/DAY() as-is for SQLite, which has no such functions."""

    def fix(node: exp.Expression) -> exp.Expression:
        for cls, fmt in _DATE_PARTS:
            if isinstance(node, cls):
                call = exp.Anonymous(
                    this="STRFTIME", expressions=[exp.Literal.string(fmt), node.this]
                )
                return exp.Cast(this=call, to=exp.DataType.build("INT"))
        return node

    return tree.transform(fix)


def transpile(text: str, dialect: str) -> str | None:
    """MySQL/Postgres -> SQLite. Any construct sqlglot can't express counts as a failed repair."""
    try:
        trees = [t for t in sqlglot.parse(text, read=dialect) if t is not None]
        parts = [
            _fix_date_parts(t).sql(dialect="sqlite", unsupported_level=ErrorLevel.RAISE)
            for t in trees
        ]
    except SqlglotError:
        return None
    parts = [_WEEK_MODIFIER.sub(lambda m: f"'{m[1]}{int(m[2]) * 7} days'", p) for p in parts]
    if not parts or any(_LEFTOVER_INTERVAL.search(p) for p in parts):
        return None
    return ";\n".join(parts) + ";"


def load_with_timeout(ctx: str, timeout_s: float) -> tuple[sqlite3.Connection | None, str]:
    conn = sqlite3.connect(":memory:")
    deadline = time.monotonic() + timeout_s
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        conn.executescript(ctx)
    except sqlite3.Error as exc:
        conn.close()
        return None, str(exc)
    conn.set_progress_handler(None, 0)
    return conn, ""


def _load_context(rec: Record, timeout_s: float):
    cleaned = pre_clean(rec.context_raw)
    conn, err = load_with_timeout(cleaned, timeout_s)
    if conn:
        return conn, cleaned, None, ""
    for dialect in DIALECTS:
        fixed = transpile(cleaned, dialect)
        if fixed and (conn := load_with_timeout(fixed, timeout_s)[0]):
            return conn, fixed, dialect, ""
    return None, "", None, err


def _try_sql(conn, sql: str, timeout_s: float, max_rows: int):
    return run_select(conn, sql, timeout_s=timeout_s, max_rows=max_rows)


def _repair_sql(conn, rec: Record, timeout_s: float, max_rows: int):
    for dialect in DIALECTS:
        fixed = transpile(rec.sql_raw, dialect)  # always from the original text
        if not fixed:
            continue
        fixed = fixed.rstrip("; ")
        if scope_error(fixed)[0]:
            continue
        res = _try_sql(conn, fixed, timeout_s, max_rows)
        if res.ok:
            return fixed, dialect, res
    return None, None, None


def _has_data(conn: sqlite3.Connection) -> bool:
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    for (name,) in tables:
        if conn.execute(f'SELECT 1 FROM "{name}" LIMIT 1').fetchone():
            return True
    return False


def validate_record(rec: Record, timeout_s: float = 2.0, max_rows: int = 1000) -> Record:
    if rec.status == "dropped":
        rec.id = make_id(rec.question, rec.context_raw, rec.sql_raw)
        return rec
    try:
        _validate(rec, timeout_s, max_rows)
    finally:
        schema = rec.schema_canonical or rec.context_raw
        rec.id = make_id(rec.question, schema, rec.sql or rec.sql_raw)
    return rec


def _validate(rec: Record, timeout_s: float, max_rows: int) -> None:
    reason, tree = scope_error(rec.sql_raw)
    if reason:
        rec.drop(reason)
        return
    conn, ctx, ctx_dialect, err = _load_context(rec, timeout_s)
    if conn is None:
        rec.drop("CTX_LOAD_FAILED", err)
        return
    rec.context_sqlite = ctx
    rec.repaired = ctx_dialect is not None
    rec.repair_dialect = ctx_dialect
    sql = _SCHEMA_QUALIFIER.sub("", rec.sql_raw)
    res = _try_sql(conn, sql, timeout_s, max_rows)
    if not res.ok and res.error_class != "TIMEOUT":
        fixed, dialect, fixed_res = _repair_sql(conn, rec, timeout_s, max_rows)
        if fixed:
            sql, res, rec.repaired = fixed, fixed_res, True
            rec.repair_dialect = dialect
            tree = scope_error(sql)[1]
    if not res.ok:
        rec.drop(res.error_class or "SQL_OTHER", res.message)
        return
    rec.sql = sql
    rec.result_rows = len(res.rows)
    rec.validation_level = "result" if _has_data(conn) else "schema"
    rec.result_empty = rec.validation_level == "result" and not res.rows
    rec.order_matters = has_order_by(tree)
    rec.complexity_derived = derive_complexity(tree)
    rec.schema_canonical = canonicalize(conn)
    rec.n_tables = rec.schema_canonical.count("CREATE TABLE")
    if not rec.complexity:
        rec.complexity = rec.complexity_derived
    conn.close()


def validate_all(records: Iterable[Record], timeout_s: float, max_rows: int, workers: int):
    work = partial(validate_record, timeout_s=timeout_s, max_rows=max_rows)
    if workers <= 1:
        return [work(r) for r in records]
    with Pool(workers) as pool:
        return list(pool.imap(work, records, chunksize=500))
