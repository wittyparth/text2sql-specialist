"""Ask both models, run what they return, compare to a reference. No UI code in here."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..eval.client import ChatClient, Completion
from ..prompt import build_messages, extract_sql
from ..sqlexec import QueryResult, results_match, run_select


@dataclass
class Backend:
    name: str
    client: ChatClient


@dataclass
class Outcome:
    name: str
    available: bool = True
    sql: str = ""
    ok: bool = False
    error: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    n_rows: int = 0
    truncated: bool = False
    latency_s: float = 0.0
    matches: bool | None = None  # only when a reference answer exists


def _outcome(name: str, comp: Completion, conn, ref: QueryResult | None, ordered: bool, show: int):
    if comp.error:
        return Outcome(name, available=False, error="model unavailable")
    sql = extract_sql(comp.text)
    if not sql:
        return Outcome(name, latency_s=comp.latency_s, error="The model didn't return a SQL query.")
    res = run_select(conn, sql, timeout_s=5, max_rows=1000)
    out = Outcome(name, sql=sql, latency_s=comp.latency_s)
    if not res.ok:
        out.error = res.message
        return out
    out.ok, out.columns, out.n_rows, out.truncated = True, res.columns, len(res.rows), res.truncated
    out.rows = res.rows[:show]
    if ref is not None and ref.ok:
        out.matches = results_match(res.rows, ref.rows, ordered)
    return out


def compare(
    backends: list[Backend],
    schema: str,
    question: str,
    conn,
    reference_sql: str | None = None,
    ordered: bool = False,
    sequential: bool = False,
    max_rows: int = 50,
) -> list[Outcome]:
    """LLM calls may run in parallel; SQL runs on the calling thread (SQLite connections are not
    shareable across threads in general)."""
    messages = build_messages(schema, question)
    ask = lambda b: b.client.complete(messages)  # noqa: E731
    if sequential:
        comps = [ask(b) for b in backends]
    else:
        with ThreadPoolExecutor(len(backends)) as pool:
            comps = list(pool.map(ask, backends))
    ref = run_select(conn, reference_sql, timeout_s=5, max_rows=1000) if reference_sql else None
    return [
        _outcome(b.name, c, conn, ref, ordered, max_rows)
        for b, c in zip(backends, comps, strict=True)
    ]
