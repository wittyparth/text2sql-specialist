"""Canonical schema text: one serialization used in training data, eval prompts and the app."""

import re
import sqlite3
import time

_PLAIN_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED = {
    "order",
    "group",
    "index",
    "table",
    "select",
    "from",
    "where",
    "key",
    "default",
    "check",
    "references",
    "primary",
    "values",
    "limit",
    "offset",
    "join",
    "left",
    "right",
    "union",
    "transaction",
    "desc",
    "asc",
    "case",
    "when",
    "end",
    "as",
    "on",
    "in",
    "is",
    "not",
    "null",
}


def _ident(name: str) -> str:
    if _PLAIN_IDENT.match(name) and name.lower() not in _RESERVED:
        return name
    return '"' + name.replace('"', '""') + '"'


def _q(name: str) -> str:
    """Quote for use inside our own PRAGMA / SELECT statements."""
    return '"' + name.replace('"', '""') + '"'


def _value(v: object, max_chars: int) -> str:
    return "NULL" if v is None else str(v).replace("\n", " ")[:max_chars]


def _table_line(conn: sqlite3.Connection, table: str) -> str:
    cols = conn.execute(f"PRAGMA table_info({_q(table)})").fetchall()
    fks = {r[3]: (r[2], r[4]) for r in conn.execute(f"PRAGMA foreign_key_list({_q(table)})")}
    pk_cols = [c[1] for c in sorted((c for c in cols if c[5]), key=lambda c: c[5])]
    composite = len(pk_cols) > 1
    parts = []
    for _cid, name, ctype, _notnull, _default, pk in cols:
        part = f"{_ident(name)} {ctype or 'TEXT'}"
        if pk and not composite:
            part += " PRIMARY KEY"
        if name in fks:
            ref_table, ref_col = fks[name]
            part += f" REFERENCES {_ident(ref_table)}({_ident(ref_col) if ref_col else ''})"
        parts.append(part)
    if composite:
        parts.append(f"PRIMARY KEY ({', '.join(_ident(c) for c in pk_cols)})")
    return f"CREATE TABLE {_ident(table)} ({', '.join(parts)});"


def canonicalize(conn: sqlite3.Connection, sample_rows: int = 2, max_value_chars: int = 30) -> str:
    lines: list[str] = []
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    for (table,) in tables:
        lines.append(_table_line(conn, table))
        if sample_rows:
            for row in conn.execute(f"SELECT * FROM {_q(table)} LIMIT {int(sample_rows)}"):
                lines.append("-- " + ", ".join(_value(v, max_value_chars) for v in row))
    views = conn.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")
    lines.extend(f"-- VIEW {name}" for (name,) in views)
    return "\n".join(lines)


def load_context(ddl: str, timeout_s: float | None = None) -> sqlite3.Connection:
    """Build an in-memory database from CREATE TABLE / INSERT text. Raises sqlite3.Error."""
    conn = sqlite3.connect(":memory:")
    if timeout_s:
        deadline = time.monotonic() + timeout_s
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        conn.executescript(ddl)
    except sqlite3.Error:
        conn.close()
        raise
    conn.set_progress_handler(None, 0)
    return conn
