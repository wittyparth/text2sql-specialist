"""The prompt contract. Training, eval and the app all build prompts through this module,
so a measured gain can't come from the model seeing a different format at test time."""

import re

SYSTEM_PROMPT = (
    "You are a SQLite expert. Given a database schema and a question, write one SQLite SELECT "
    "query that answers the question. Output only the SQL query."
)

_FENCE = re.compile(r"```(?:sqlite|sql)?[ \t]*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
_LABEL = re.compile(r"^\s*(?:sql|answer|query)\s*:\s*", re.IGNORECASE)
_STARTS_LIKE_SQL = re.compile(r"\b(select|with)\b", re.IGNORECASE)


def build_messages(schema: str, question: str, answer_sql: str | None = None) -> list[dict]:
    # schema first, question last: system + schema is a stable prefix the server can cache
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Schema:\n{schema}\n\nQuestion: {question}"},
    ]
    if answer_sql is not None:
        msgs.append({"role": "assistant", "content": answer_sql})
    return msgs


def _first_statement(text: str) -> str:
    """Cut at the first ';' that isn't inside a quoted string or identifier."""
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"', "`"):
            quote = ch
        elif ch == ";":
            return text[:i]
    return text


def extract_sql(text: str) -> str:
    """Pull one SQL statement out of a model reply. Same code for every model we compare."""
    m = _FENCE.search(text)
    body = m.group(1) if m else text
    body = _LABEL.sub("", body.strip())
    sql = _first_statement(body).strip()
    return sql if _STARTS_LIKE_SQL.search(sql) else ""
