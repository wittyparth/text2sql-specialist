import json

import httpx
import pytest

from text2sql.app.core import Backend, compare
from text2sql.app.databases import CustomSchemaError, load_custom, load_presets
from text2sql.eval.client import ChatClient
from text2sql.schema import load_context

DDL = (
    "CREATE TABLE pets (id INT, name TEXT, age INT);"
    " INSERT INTO pets VALUES (1, 'Rex', 3), (2, 'Tom', 5);"
)


def backend(name, reply=None, status=200):
    def handler(request):
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    client = ChatClient("http://x/v1", name)
    client.http = httpx.Client(base_url="http://x/v1", transport=httpx.MockTransport(handler))
    return Backend(name, client)


def test_compare_marks_match_and_error_per_model():
    conn = load_context(DDL)
    good = backend("ft", "SELECT name FROM pets WHERE age > 4")
    bad = backend("base", "SELECT nm FROM pets")
    base, ft = compare(
        [bad, good],
        "schema",
        "who is older than 4?",
        conn,
        reference_sql="SELECT name FROM pets WHERE age > 4",
    )[:2]
    assert not base.ok and "no such column" in base.error
    assert ft.ok and ft.matches is True and ft.rows == [("Tom",)]


def test_one_backend_down_does_not_break_the_other():
    conn = load_context(DDL)
    outs = compare(
        [backend("base", status=500), backend("ft", "SELECT count(*) FROM pets")],
        "s",
        "how many?",
        conn,
        sequential=True,
    )
    assert not outs[0].available and outs[0].error == "model unavailable"
    assert outs[1].ok and outs[1].rows == [(2,)]


def test_write_query_from_a_model_is_blocked_not_executed():
    conn = load_context(DDL)
    out = compare([backend("ft", "WITH x AS (SELECT 1) DELETE FROM pets")], "s", "q", conn)[0]
    assert not out.ok and "not authorized" in out.error.lower()
    assert conn.execute("SELECT count(*) FROM pets").fetchone() == (2,)


def test_no_sql_in_reply_is_a_readable_message():
    out = compare([backend("ft", "Sorry, I can't help.")], "s", "q", load_context(DDL))[0]
    assert out.error and "didn't return" in out.error


def test_rows_are_capped_for_display_only():
    conn = load_context("CREATE TABLE t (a);" + "INSERT INTO t VALUES (1);" * 80)
    out = compare([backend("ft", "SELECT a FROM t")], "s", "q", conn, max_rows=50)[0]
    assert len(out.rows) == 50 and out.n_rows == 80


@pytest.mark.parametrize(
    "bad",
    [
        "DROP TABLE x;",
        "CREATE TABLE t (a INT); ATTACH DATABASE 'x.db' AS y;",
        "CREATE TABLE t (a INT); PRAGMA writable_schema = 1;",
        "CREATE TABLE t (a INT); DELETE FROM t;",
        "",
    ],
)
def test_custom_schema_rejects_everything_but_create_and_insert(bad):
    with pytest.raises(CustomSchemaError):
        load_custom(bad)


def test_custom_schema_size_cap_and_broken_sql():
    with pytest.raises(CustomSchemaError, match="KB"):
        load_custom("CREATE TABLE t (a INT);" + "INSERT INTO t VALUES (1);" * 1000)
    with pytest.raises(CustomSchemaError):
        load_custom("CREATE TABLE t (a INT, ;")


def test_custom_schema_loads_and_canonicalizes():
    conn, schema = load_custom(DDL)
    assert schema.startswith("CREATE TABLE pets (id INT, name TEXT, age INT);")
    conn.close()


def test_presets_load_from_the_committed_demo_files(chinook_path):
    presets = load_presets(chinook_path.parent)
    assert "chinook" in presets and "CREATE TABLE Album" in presets["chinook"].schema
    assert any(p.unseen for p in presets.values())
    spec = json.loads((chinook_path.parent / "examples.json").read_text())
    assert all(e["question"] and e["sql"] for p in spec["presets"] for e in p["examples"])


def test_ui_builds(chinook_path):
    pytest.importorskip("gradio")
    from text2sql.app.main import Settings, build_ui
    from text2sql.app.warmup import WarmupState

    presets = load_presets(chinook_path.parent)
    demo = build_ui(
        Settings.from_env(),
        presets,
        [backend("base", "SELECT 1"), backend("ft", "SELECT 1")],
        WarmupState(),
    )
    assert demo is not None


def test_dead_backend_fails_fast_when_configured_to():
    import time

    client = ChatClient("http://x/v1", "m", backoff=(0, 0))
    client.http = httpx.Client(
        base_url="http://x/v1", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    started = time.monotonic()
    assert client.complete([]).error
    assert time.monotonic() - started < 1
