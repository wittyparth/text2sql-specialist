"""Stage 02: turn raw source rows into partial Records (text clean-up only, nothing executed)."""

import re

from .records import Record

_SPACE_BEFORE_Q = re.compile(r"\s+\?")


def normalize_question(text: str) -> str:
    return _SPACE_BEFORE_Q.sub("?", re.sub(r"\s+", " ", text or "").strip())


def normalize_sql(sql: str) -> str:
    """Collapse whitespace and drop a trailing ';', leaving quoted text untouched."""
    out: list[str] = []
    quote = None
    pending_space = False
    for ch in (sql or "").strip():
        if quote:
            out.append(ch)
            quote = None if ch == quote else quote
        elif ch in ("'", '"', "`"):
            if pending_space:
                out.append(" ")
                pending_space = False
            out.append(ch)
            quote = ch
        elif ch.isspace():
            pending_space = bool(out)
        else:
            if pending_space:
                out.append(" ")
                pending_space = False
            out.append(ch)
    return "".join(out).rstrip("; ")


def normalize_context(ctx: str) -> str:
    ctx = (ctx or "").strip()
    return ctx if not ctx or ctx.endswith(";") else ctx + ";"


def _finish(rec: Record) -> Record:
    if not (rec.question and rec.context_raw and rec.sql_raw):
        rec.drop("EMPTY_FIELD", "question, context or sql is empty")
    return rec


def map_gretel(key: str, row: dict) -> Record:
    return _finish(
        Record(
            source_row_key=key,
            source="gretel",
            source_id=str(row["id"]),
            domain=row.get("domain") or "unknown",
            complexity=row.get("sql_complexity") or "",
            task_type=row.get("sql_task_type") or "",
            question=normalize_question(row.get("sql_prompt")),
            context_raw=normalize_context(row.get("sql_context")),
            sql_raw=normalize_sql(row.get("sql")),
        )
    )


def map_sqlcc(key: str, row: dict) -> Record:
    return _finish(
        Record(
            source_row_key=key,
            source="sqlcc",
            source_id=None,
            domain="sqlcc",
            task_type="data retrieval",
            question=normalize_question(row.get("question")),
            context_raw=normalize_context(row.get("context")),
            sql_raw=normalize_sql(row.get("answer")),
        )
    )


MAPPERS = {"gretel": map_gretel, "sqlcc": map_sqlcc}
