import sqlite3

from text2sql.schema import canonicalize, load_context
from text2sql.sqlexec import safe_connect


def test_chinook_matches_golden(chinook_path, tmp_path):
    golden = (chinook_path.parent.parent.parent / "tests/golden/chinook_canonical.txt").read_text()
    assert canonicalize(safe_connect(chinook_path)) == golden


def test_deterministic(chinook_path):
    conn = safe_connect(chinook_path)
    assert canonicalize(conn) == canonicalize(conn)


def test_basic_format_and_foreign_keys():
    conn = load_context(
        "CREATE TABLE b (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE a (id INTEGER PRIMARY KEY, b_id INTEGER REFERENCES b(id), note);"
        "INSERT INTO b VALUES (1, 'x'); INSERT INTO a VALUES (7, 1, NULL);"
    )
    assert canonicalize(conn).splitlines() == [
        "CREATE TABLE a (id INTEGER PRIMARY KEY, b_id INTEGER REFERENCES b(id), note TEXT);",
        "-- 7, 1, NULL",
        "CREATE TABLE b (id INTEGER PRIMARY KEY, name TEXT);",
        "-- 1, x",
    ]


def test_quotes_awkward_identifiers():
    conn = load_context('CREATE TABLE "order items" ("group" INTEGER, "unit price" REAL);')
    out = canonicalize(conn, sample_rows=0)
    assert out == 'CREATE TABLE "order items" ("group" INTEGER, "unit price" REAL);'
    # the quoted output has to be valid SQL again
    sqlite3.connect(":memory:").executescript(out)


def test_long_values_are_cut_and_newlines_flattened():
    conn = load_context("CREATE TABLE t (v TEXT); INSERT INTO t VALUES ('" + "x" * 50 + "\ny');")
    row = canonicalize(conn).splitlines()[1]
    assert row == "-- " + "x" * 30


def test_round_trip_recreates_tables(chinook_path):
    ddl = canonicalize(safe_connect(chinook_path), sample_rows=0)
    fresh = sqlite3.connect(":memory:")
    fresh.executescript(ddl)
    names = {r[0] for r in fresh.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"Album", "Track", "PlaylistTrack"} <= names


def test_views_are_listed_without_body():
    conn = load_context("CREATE TABLE t (a INTEGER); CREATE VIEW v AS SELECT a FROM t;")
    assert canonicalize(conn, sample_rows=0).splitlines()[-1] == "-- VIEW v"


def test_composite_primary_key_is_a_table_constraint():
    conn = load_context("CREATE TABLE pt (a INTEGER, b INTEGER, PRIMARY KEY (a, b));")
    out = canonicalize(conn, sample_rows=0)
    assert out == "CREATE TABLE pt (a INTEGER, b INTEGER, PRIMARY KEY (a, b));"
