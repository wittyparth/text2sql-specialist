import json
import sqlite3
from pathlib import Path

import pytest

from text2sql.etl.config import Config
from text2sql.etl.extract import (
    check_readable,
    ensure_source,
    iter_gretel,
    iter_sqlcc,
    with_retries,
)
from text2sql.etl.manifest import Manifest

from . import fixtures as fx


def make_cfg(tmp_path: Path, sha: str | None = None) -> Config:
    return Config(
        sources={
            "chinook": {
                "kind": "url",
                "url": "http://example.invalid/db.sqlite",
                "files": ["db.sqlite"],
                "revision": "v1",
                "sha256": sha,
            }
        },
        paths={"raw": tmp_path / "raw", "state": tmp_path / "state"},
        sample={"class_weights": {}},
    )


def fake_sqlite(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(dest)
    conn.execute("CREATE TABLE a (x INT)")
    conn.commit()
    conn.close()


def test_second_run_downloads_nothing(tmp_path):
    cfg, manifest = make_cfg(tmp_path), Manifest(tmp_path / "m.json")
    calls = []
    fetch = lambda u, d: (calls.append(u), fake_sqlite(u, d))  # noqa: E731
    assert ensure_source("chinook", cfg, manifest, fetch)[1] == 1
    assert ensure_source("chinook", cfg, manifest, fetch)[1] == 0
    assert len(calls) == 1


def test_deleted_file_is_refetched(tmp_path):
    cfg, manifest = make_cfg(tmp_path), Manifest(tmp_path / "m.json")
    paths, _ = ensure_source("chinook", cfg, manifest, fake_sqlite)
    paths[0].unlink()
    assert ensure_source("chinook", cfg, manifest, fake_sqlite)[1] == 1


def test_retries_then_succeeds():
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError("boom")

    with_retries(flaky, delays=(0, 0, 0), sleep=lambda s: None)
    assert len(attempts) == 3


def test_gives_up_after_three_attempts():
    with pytest.raises(OSError):
        with_retries(
            lambda: (_ for _ in ()).throw(OSError("down")), delays=(0, 0, 0), sleep=lambda s: None
        )


def test_checksum_mismatch_is_rejected_and_not_kept(tmp_path):
    cfg, manifest = make_cfg(tmp_path, sha="0" * 64), Manifest(tmp_path / "m.json")
    with pytest.raises(OSError, match="sha256"):
        ensure_source("chinook", cfg, manifest, fake_sqlite)
    assert not (tmp_path / "raw/chinook/v1/db.sqlite").exists()


def test_truncated_download_never_becomes_the_real_file(tmp_path):
    from text2sql.etl.extract import download_url

    dest = tmp_path / "x.sqlite"

    class Boom:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            raise OSError("connection reset")

    import urllib.request

    orig = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: Boom()
    try:
        with pytest.raises(OSError):
            download_url("http://example.invalid", dest)
    finally:
        urllib.request.urlopen = orig
    assert not dest.exists()


def test_readers_skip_known_keys_and_respect_limit(tmp_path):
    g = tmp_path / "synthetic_text_to_sql_train.snappy.parquet"
    fx.synthetic_gretel(g, n_domains=2, per_domain=3)
    keys = [k for k, _ in iter_gretel([g], set(), None)]
    assert len(keys) == 6 and keys[0].startswith("gretel:train:")
    assert len(list(iter_gretel([g], set(), 4))) == 4
    assert len(list(iter_gretel([g], {keys[0]}, None))) == 5
    s = tmp_path / "sqlcc.json"
    fx.synthetic_sqlcc(s, 5)
    assert [k for k, _ in iter_sqlcc([s], set(), 2)] == ["sqlcc:0", "sqlcc:1"]


def test_check_readable_rejects_empty_sqlite_and_bad_json(tmp_path):
    empty = tmp_path / "e.sqlite"
    sqlite3.connect(empty).close()
    with pytest.raises(OSError):
        check_readable(empty)
    bad = tmp_path / "b.json"
    bad.write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        check_readable(bad)
