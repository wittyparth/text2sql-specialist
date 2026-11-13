"""Rule-based failure taxonomy for wrong predictions (see plan/04-evaluation/error-analysis.md)."""

from collections import Counter

from ..sqlexec import QueryResult, results_match

CLASSES = [
    "EMPTY_OUTPUT",
    "DIALECT",
    "SCHEMA_LINK",
    "AMBIGUOUS",
    "SYNTAX",
    "TIMEOUT",
    "WRONG_PROJECTION",
    "WRONG_ROWCOUNT",
    "WRONG_VALUES",
    "WRONG_ORDER",
    "OTHER_ERROR",
]

_FROM_ERROR_CLASS = {
    "SQL_NO_SUCH_FUNCTION": "DIALECT",
    "SQL_NO_SUCH_COLUMN": "SCHEMA_LINK",
    "SQL_NO_SUCH_TABLE": "SCHEMA_LINK",
    "SQL_AMBIGUOUS": "AMBIGUOUS",
    "SQL_SYNTAX": "SYNTAX",
    "TIMEOUT": "TIMEOUT",
}


def classify(sql: str, pred: QueryResult | None, gold: QueryResult, ordered: bool) -> str:
    """Return the failure class of a prediction already known to be wrong."""
    if not sql:
        return "EMPTY_OUTPUT"
    if pred is None or not pred.ok:
        code = pred.error_class if pred else ""
        return _FROM_ERROR_CLASS.get(code, "OTHER_ERROR")
    if pred.rows and gold.rows and len(pred.rows[0]) != len(gold.rows[0]):
        return "WRONG_PROJECTION"
    if len(pred.rows) != len(gold.rows):
        return "WRONG_ROWCOUNT"
    if ordered and results_match(pred.rows, gold.rows, ordered=False):
        return "WRONG_ORDER"
    return "WRONG_VALUES"


def shift_table(base: list[str], tuned: list[str]) -> dict[str, tuple[int, int]]:
    b, t = Counter(base), Counter(tuned)
    return {c: (b[c], t[c]) for c in CLASSES if b[c] or t[c]}
