"""Stage 01: fetch pinned source files (cached by checksum) and stream rows out of them."""

import hashlib
import json
import logging
import os
import sqlite3
import time
import urllib.request
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from .config import Config, SourceCfg
from .manifest import Manifest

log = logging.getLogger("etl.extract")

BACKOFF_S = (1, 4, 16)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def with_retries(fn: Callable[[], None], delays=BACKOFF_S, sleep=time.sleep) -> None:
    for attempt, delay in enumerate(delays, start=1):
        try:
            return fn()
        except (OSError, RuntimeError) as exc:
            if attempt == len(delays):
                raise
            log.warning("attempt %d failed (%s); retrying in %ss", attempt, exc, delay)
            sleep(delay)


def download_url(url: str, dest: Path) -> None:
    """Write to dest.part and only promote it once the whole body arrived."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(url, timeout=60) as resp, part.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    if part.stat().st_size == 0:
        part.unlink()
        raise OSError(f"empty download from {url}")
    os.replace(part, dest)


def _fetch_hf(repo: str, filename: str, revision: str, dest_dir: Path) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(
        hf_hub_download(
            repo_id=repo,
            filename=filename,
            repo_type="dataset",
            revision=revision,
            local_dir=dest_dir,
        )
    )


def check_readable(path: Path) -> None:
    """Cheap sanity check so a truncated or wrong file fails here, not three stages later."""
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        pq.ParquetFile(path).metadata  # noqa: B018 - raises on a bad footer
    elif path.suffix == ".json":
        json.loads(path.read_text())
    elif path.suffix in (".sqlite", ".db"):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        n = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        conn.close()
        if n == 0:
            raise OSError(f"{path} has no tables")


def ensure_source(
    name: str,
    cfg: Config,
    manifest: Manifest,
    fetch_url: Callable[[str, Path], None] = download_url,
) -> tuple[list[Path], int]:
    """Return local paths for one source and how many files had to be downloaded."""
    src: SourceCfg = cfg.sources[name]
    dest_dir = cfg.paths.raw / name / src.revision
    paths, downloaded = [], 0
    for filename in src.files:
        if src.kind == "local":
            paths.append(Path(filename))
            continue
        path = dest_dir / filename
        key = f"{name}/{src.revision}/{filename}"
        entry = manifest.file_entry(key)
        cached = path.exists() and entry and sha256_file(path) == entry["sha256"]
        if not cached:
            if src.kind == "hf":
                with_retries(lambda f=filename: _fetch_hf(src.repo, f, src.revision, dest_dir))
            else:
                with_retries(lambda p=path: fetch_url(src.url, p))
            check_readable(path)
            digest = sha256_file(path)
            if src.sha256 and digest != src.sha256:
                path.unlink()
                raise OSError(f"{filename}: sha256 {digest} != pinned {src.sha256}")
            manifest.set_file(
                key,
                {
                    "revision": src.revision,
                    "sha256": digest,
                    "bytes": path.stat().st_size,
                    "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                },
            )
            downloaded += 1
        paths.append(path)
    return paths, downloaded


def file_label(path: Path) -> str:
    """'train' / 'test' for the Gretel files; used to keep their id spaces apart."""
    for label in ("train", "test"):
        if f"_{label}" in path.name:
            return label
    return path.stem


def iter_gretel(paths: list[Path], skip: set[str], limit: int | None) -> Iterator[tuple[str, dict]]:
    import pyarrow.parquet as pq

    seen = 0
    for path in paths:
        label = file_label(path)
        for batch in pq.ParquetFile(path).iter_batches(batch_size=10_000):
            for row in batch.to_pylist():
                if limit is not None and seen >= limit:
                    return
                seen += 1
                key = f"gretel:{label}:{row['id']}"
                if key not in skip:
                    yield key, row


def iter_sqlcc(paths: list[Path], skip: set[str], limit: int | None) -> Iterator[tuple[str, dict]]:
    # 21 MB, so a plain json.load is fine; ijson would be the choice if this were 100x bigger
    rows = json.loads(paths[0].read_text())
    for i, row in enumerate(rows[:limit]):
        key = f"sqlcc:{i}"
        if key not in skip:
            yield key, row
