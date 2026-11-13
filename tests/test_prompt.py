from text2sql.prompt import SYSTEM_PROMPT, build_messages, extract_sql


def test_messages_shape():
    msgs = build_messages("CREATE TABLE t (a INTEGER);", "how many rows?")
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == SYSTEM_PROMPT
    assert msgs[1]["content"] == "Schema:\nCREATE TABLE t (a INTEGER);\n\nQuestion: how many rows?"


def test_answer_is_appended_as_assistant_turn():
    msgs = build_messages("s", "q", answer_sql="SELECT 1")
    assert msgs[-1] == {"role": "assistant", "content": "SELECT 1"}


def test_extract_plain_and_fenced():
    assert extract_sql("SELECT a FROM t") == "SELECT a FROM t"
    assert extract_sql("Here you go:\n```sql\nSELECT a FROM t;\n```\nHope it helps") == (
        "SELECT a FROM t"
    )
    assert extract_sql("```\nSELECT 1\n```") == "SELECT 1"
    assert extract_sql("```sqlite\nSELECT 1\n```") == "SELECT 1"


def test_extract_strips_labels_and_extra_statements():
    assert extract_sql("SQL: SELECT 1; SELECT 2") == "SELECT 1"
    assert extract_sql("Answer:  WITH x AS (SELECT 1) SELECT * FROM x") == (
        "WITH x AS (SELECT 1) SELECT * FROM x"
    )


def test_semicolon_inside_string_literal_is_kept():
    assert extract_sql("SELECT 'a;b' AS x; DROP TABLE t") == "SELECT 'a;b' AS x"


def test_no_sql_gives_empty_string():
    assert extract_sql("") == ""
    assert extract_sql("I cannot answer that.") == ""


def test_fence_tag_sqlite_is_not_left_behind():
    assert extract_sql("```sqlite\nSELECT 1\n```") == "SELECT 1"
