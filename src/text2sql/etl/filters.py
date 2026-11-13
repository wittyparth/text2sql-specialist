"""Stage 05: scope and quality filters, plus the time-dependence flag."""

import re
from collections import Counter

from .config import FiltersCfg
from .records import Record

RELATIVE_QUESTION = re.compile(
    r"\b(last|past|previous|recent|this|current)\s+(\d+\s+)?(day|week|month|quarter|year)s?\b"
    r"|\b(today|yesterday|ytd)\b",
    re.I,
)
NOW_FUNCTION = re.compile(
    r"now\(|current_date|current_timestamp|curdate|getdate|sysdate|date\('now'", re.I
)
HARDCODED_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def flag_time_dependence(rec: Record) -> None:
    rec.time_dependent = bool(
        NOW_FUNCTION.search(rec.sql) or RELATIVE_QUESTION.search(rec.question)
    )


def _reason(rec: Record, cfg: FiltersCfg) -> str | None:
    if not cfg.question_min_chars <= len(rec.question) <= cfg.question_max_chars:
        return "QUESTION_LENGTH"
    if len(rec.sql) > cfg.sql_max_chars:
        return "SQL_LENGTH"
    if rec.n_tokens > cfg.token_budget:
        return "TOKEN_BUDGET"
    relative = bool(RELATIVE_QUESTION.search(rec.question))
    if relative and HARDCODED_DATE.search(rec.sql) and not NOW_FUNCTION.search(rec.sql):
        return "TIME_RELATIVE_HARDCODED"
    return None


def apply_filters(records: list[Record], cfg: FiltersCfg) -> Counter:
    dropped: Counter = Counter()
    for rec in records:
        if rec.status != "kept":
            continue
        flag_time_dependence(rec)
        if reason := _reason(rec, cfg):
            rec.drop(reason)
            dropped[reason] += 1
    return dropped
