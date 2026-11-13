import json

import httpx
import pytest

from text2sql.eval.client import ChatClient
from text2sql.eval.errors import classify, shift_table
from text2sql.eval.run import EvalError, load_items, score_item
from text2sql.eval.score import bootstrap_ci, mcnemar_exact, paired_bootstrap, summarize
from text2sql.schema import load_context
from text2sql.sqlexec import run_select


def test_ci_of_all_correct_is_one():
    assert bootstrap_ci([True] * 50) == (1.0, 1.0)
    assert bootstrap_ci([False] * 50) == (0.0, 0.0)


def test_ci_brackets_the_mean_and_is_seeded():
    hits = [True] * 60 + [False] * 40
    lo, hi = bootstrap_ci(hits)
    assert lo < 0.6 < hi and (lo, hi) == bootstrap_ci(hits)
    assert 0.45 < lo and hi < 0.75


def test_mcnemar_no_discordant_pairs_is_one():
    assert mcnemar_exact(0, 0) == 1.0


def test_mcnemar_known_values():
    assert mcnemar_exact(0, 10) == pytest.approx(2 / 1024)
    assert mcnemar_exact(5, 5) == 1.0


def test_paired_bootstrap_detects_improvement():
    a = [False] * 40 + [True] * 60
    b = [True] * 30 + [False] * 10 + [True] * 60  # fixes 30, breaks none
    diff, lo, hi = paired_bootstrap(a, b)
    assert diff == pytest.approx(0.30) and lo > 0
    with pytest.raises(ValueError):
        paired_bootstrap([True], [True, False])


def rows(spec):
    return [
        {
            "status": "scored",
            "difficulty": d,
            "ok": ok,
            "ok_strict": ok,
            "executed": ex,
            "failure": f,
            "latency_s": 0.5,
            "completion_tokens": 20,
        }
        for d, ok, ex, f in spec
    ]


def test_summary_counts_and_difficulty_n():
    s = summarize(
        rows(
            [
                ("easy", True, True, None),
                ("easy", False, False, "DIALECT"),
                ("hard", False, True, "WRONG_VALUES"),
            ]
        )
    )
    assert s["n"] == 3 and s["ex"] == pytest.approx(1 / 3)
    assert s["by_difficulty"]["easy"] == {"n": 2, "ex": 0.5}
    assert s["dialect_error_rate"] == pytest.approx(1 / 3)
    assert s["valid_sql_rate"] == pytest.approx(2 / 3)


def test_endpoint_errors_are_not_scored_as_wrong_sql():
    data = rows([("easy", True, True, None)]) + [{"status": "endpoint_error", "difficulty": "easy"}]
    s = summarize(data)
    assert s["n"] == 1 and s["endpoint_errors"] == 1 and s["ex"] == 1.0


def conn():
    return load_context("CREATE TABLE t (a INT, b INT); INSERT INTO t VALUES (1, 2), (3, 4);")


def test_failure_taxonomy():
    c = conn()
    gold = run_select(c, "SELECT a, b FROM t ORDER BY a")
    case = lambda sql, ordered=False: classify(  # noqa: E731
        sql, run_select(c, sql) if sql else None, gold, ordered
    )
    assert case("") == "EMPTY_OUTPUT"
    assert case("SELECT zz FROM t") == "SCHEMA_LINK"
    assert case("SELECT YEAR(a) FROM t") == "DIALECT"
    assert case("SELEC a") == "SYNTAX"
    assert case("SELECT a FROM t") == "WRONG_PROJECTION"
    assert case("SELECT a, b FROM t WHERE a = 1") == "WRONG_ROWCOUNT"
    assert case("SELECT b, a + 1 FROM t") == "WRONG_VALUES"
    assert case("SELECT a, b FROM t ORDER BY a DESC", ordered=True) == "WRONG_ORDER"


def test_shift_table():
    assert shift_table(["DIALECT", "SCHEMA_LINK", "SCHEMA_LINK"], ["SCHEMA_LINK"]) == {
        "DIALECT": (1, 0),
        "SCHEMA_LINK": (2, 1),
    }


def test_score_item_dialect_vs_correct_and_write_block():
    c = conn()
    gold = run_select(c, "SELECT a FROM t")
    item = {"order_matters": False}
    assert score_item(item, "```sql\nSELECT a FROM t;\n```", c, gold)["ok"]
    bad = score_item(item, "SELECT YEAR(a) FROM t", c, gold)
    assert not bad["ok"] and bad["failure"] == "DIALECT"
    assert score_item(item, "DELETE FROM t", c, gold)["failure"] == "EMPTY_OUTPUT"  # never run
    evil = score_item(item, "WITH x AS (SELECT 1) DELETE FROM t", c, gold)
    assert not evil["ok"] and evil["error_class"] == "NOT_AUTHORIZED"
    assert run_select(c, "SELECT count(*) FROM t").rows == [(2,)]


def test_modified_eval_file_is_refused(tmp_path):
    f = tmp_path / "e.jsonl"
    f.write_text('{"id": "x"}\n')
    cfg = {"path": str(f), "sha256": "0" * 64}
    with pytest.raises(EvalError, match="frozen"):
        load_items(cfg)


def make_client(handler):
    client = ChatClient("http://x/v1", "m")
    client.http = httpx.Client(base_url="http://x/v1", transport=httpx.MockTransport(handler))
    return client


def test_client_retries_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(500, text="context exceeded")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "SELECT 1"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            },
        )

    out = make_client(handler).complete([{"role": "user", "content": "q"}], sleep=lambda s: None)
    assert out.text == "SELECT 1" and out.error is None and len(calls) == 3


def test_client_reports_endpoint_error_after_three_failures():
    out = make_client(lambda r: httpx.Response(500)).complete([], sleep=lambda s: None)
    assert out.error and out.text == ""


def test_client_sends_model_stop_and_seed():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    make_client(handler).complete([{"role": "user", "content": "q"}])
    assert seen["model"] == "m" and seen["stop"] == ["<|im_end|>"] and seen["temperature"] == 0
