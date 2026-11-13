"""Training/serving parity: the model must see in the app what it saw in training."""

import json
from pathlib import Path

import httpx
import pyarrow.parquet as pq
import pytest

from text2sql.app.core import Backend, compare
from text2sql.eval.client import ChatClient
from text2sql.prompt import build_messages
from text2sql.schema import canonicalize, load_context
from text2sql.sqlexec import results_match, run_select

DDL = (
    "CREATE TABLE pets (id INT, name TEXT, age INT);"
    " INSERT INTO pets VALUES (1, 'Rex', 3), (2, 'Tom', 5);"
)
PROCESSED = Path("data/processed")


def backend_replying(reply: str, sent: list | None = None) -> Backend:
    def handler(request):
        if sent is not None:
            sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    client = ChatClient("http://x/v1", "m")
    client.http = httpx.Client(base_url="http://x/v1", transport=httpx.MockTransport(handler))
    return Backend("m", client)


def test_app_request_matches_training_prompt():
    conn = load_context(DDL)
    schema = canonicalize(conn)
    question = "who is older than 4?"
    sent: list = []
    compare([backend_replying("SELECT 1", sent)], schema, question, conn)

    trained = build_messages(schema, question, "SELECT name FROM pets WHERE age > 4")
    assert sent[0]["messages"] == trained[:2]  # same system + user, byte for byte
    assert trained[2]["role"] == "assistant"


@pytest.mark.skipif(not (PROCESSED / "train.jsonl").exists(), reason="run the pipeline first")
def test_real_training_rows_match_inference_prompt():
    by_id = {r["id"]: r for r in pq.read_table(PROCESSED / "records.parquet").to_pylist()}
    checked = 0
    with open(PROCESSED / "train.jsonl") as f:
        for line in f:
            row = json.loads(line)
            rec = by_id[row["meta"]["id"]]
            assert row["messages"][:2] == build_messages(rec["schema_canonical"], rec["question"])
            checked += 1
            if checked == 500:
                break
    assert checked > 0


def test_badge_uses_the_eval_metric():
    conn = load_context(DDL)
    gold = "SELECT id, name FROM pets ORDER BY id"
    pred = "SELECT name, id FROM pets ORDER BY id"  # same data, columns swapped
    out = compare([backend_replying(pred)], "s", "list pets", conn, reference_sql=gold)[0]
    direct = results_match(run_select(conn, pred).rows, run_select(conn, gold).rows, True)
    assert out.matches is direct is True
