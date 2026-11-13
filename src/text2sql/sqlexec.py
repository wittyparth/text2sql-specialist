"""Safe, read-only SQL execution plus the result-comparison rules used by eval and the app."""

import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}

_DATETIME_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2}) 00:00:00$")

_ERROR_CLASSES = [
    ("no such column", "SQL_NO_SUCH_COLUMN"),
    ("no such table", "SQL_NO_SUCH_TABLE"),
    ("no such function", "SQL_NO_SUCH_FUNCTION"),
    ("ambiguous column", "SQL_AMBIGUOUS"),
    ("not authorized", "NOT_AUTHORIZED"),
    ("interrupted", "TIMEOUT"),
    ("syntax error", "SQL_SYNTAX"),
]


@dataclass
class QueryResult:
    ok: bool
    rows: list[tuple] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    truncated: bool = False
    error_class: str | None = None
    message: str | None = None
    elapsed_s: float = 0.0


def classify_error(message: str) -> str:
    low = message.lower()
    for needle, label in _ERROR_CLASSES:
        if needle in low:
            return label
    if re.search(r'near ".*": syntax error', low):
        return "SQL_SYNTAX"
    return "SQL_OTHER"


def _authorizer(action, *_args) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def safe_connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a database file read-only. Only SELECT-style statements will get past run_select."""
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    return sqlite3.connect(uri, uri=True, check_same_thread=False)


def run_select(
    conn: sqlite3.Connection, sql: str, timeout_s: float = 5, max_rows: int = 1000
) -> QueryResult:
    """Run one statement under an authorizer and a time limit. Never raises."""
    deadline = time.monotonic() + timeout_s
    started = time.monotonic()
    conn.set_authorizer(_authorizer)
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(max_rows + 1)
    except (sqlite3.Error, sqlite3.Warning) as exc:
        return QueryResult(
            ok=False,
            error_class=classify_error(str(exc)),
            message=str(exc),
            elapsed_s=time.monotonic() - started,
        )
    finally:
        conn.set_progress_handler(None, 0)
        conn.set_authorizer(None)
    return QueryResult(
        ok=True,
        rows=rows[:max_rows],
        columns=columns,
        truncated=len(rows) > max_rows,
        elapsed_s=time.monotonic() - started,
    )


def _cell(v: object) -> object:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        s = _DATETIME_MIDNIGHT.sub(r"\1", s)
        try:
            return round(float(s), 2)
        except ValueError:
            return s
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return v


def _normalize(rows: list[tuple], ordered: bool):
    # sorting reprs inside each row is what makes the compare column-order insensitive
    canon = [tuple(sorted(repr(_cell(c)) for c in row)) for row in rows]
    return canon if ordered else Counter(canon)


def results_match(pred: list[tuple], gold: list[tuple], ordered: bool = False) -> bool:
    """Normalized execution match: see plan/04-evaluation/metrics.md for the rules."""
    return _normalize(pred, ordered) == _normalize(gold, ordered)


def results_match_strict(pred: list[tuple], gold: list[tuple], ordered: bool = False) -> bool:
    """No cell normalization, column order respected. Reported next to the normalized metric."""
    if ordered:
        return list(map(tuple, pred)) == list(map(tuple, gold))
    return Counter(map(tuple, pred)) == Counter(map(tuple, gold))
