"""Preset demo databases and the pasted-schema loader."""

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ..schema import canonicalize, load_context
from ..sqlexec import safe_connect

MAX_DDL_BYTES = 20_000
LOAD_TIMEOUT_S = 2.0


class CustomSchemaError(ValueError):
    """Raised with a message that is safe to show to the user."""


@dataclass
class Preset:
    key: str
    label: str
    path: Path
    schema: str
    unseen: bool
    examples: list[dict] = field(default_factory=list)

    def connect(self) -> sqlite3.Connection:
        return safe_connect(self.path)


def load_presets(demo_dir: Path) -> dict[str, Preset]:
    spec = json.loads((demo_dir / "examples.json").read_text())
    presets = {}
    for p in spec["presets"]:
        path = demo_dir / p["file"]
        if not path.exists():
            continue
        conn = safe_connect(path)
        schema = canonicalize(conn)
        conn.close()
        presets[p["key"]] = Preset(p["key"], p["label"], path, schema, p["unseen"], p["examples"])
    return presets


def load_custom(ddl: str) -> tuple[sqlite3.Connection, str]:
    """Accept CREATE TABLE and INSERT statements only; anything else is refused up front."""
    ddl = ddl.strip()
    if not ddl:
        raise CustomSchemaError("Paste some CREATE TABLE statements first.")
    if len(ddl.encode()) > MAX_DDL_BYTES:
        raise CustomSchemaError(f"That schema is over {MAX_DDL_BYTES // 1000} KB; please trim it.")
    try:
        statements = [s for s in sqlglot.parse(ddl, read="sqlite") if s is not None]
    except SqlglotError:
        raise CustomSchemaError("I couldn't parse that as SQLite DDL.") from None
    for stmt in statements:
        is_table = isinstance(stmt, exp.Create) and str(stmt.args.get("kind")).upper() == "TABLE"
        if not (is_table or isinstance(stmt, exp.Insert)):
            raise CustomSchemaError("Only CREATE TABLE and INSERT statements are allowed here.")
    try:
        conn = load_context(ddl, LOAD_TIMEOUT_S)
    except sqlite3.Error as exc:
        raise CustomSchemaError(f"SQLite rejected the schema: {exc}") from None
    schema = canonicalize(conn)
    if not schema:
        conn.close()
        raise CustomSchemaError("No tables found in that schema.")
    return conn, schema
