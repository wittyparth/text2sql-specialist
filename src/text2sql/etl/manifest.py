"""Pipeline state that has to survive between runs: what was fetched, and what each run did.

Processed row keys are *not* stored here. They are read from the interim validated table, which is
written first, so a crash between the two writes can never leave the manifest ahead of the data.
"""

import json
import os
from pathlib import Path


def atomic_write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data.encode() if isinstance(data, str) else data)
    os.replace(tmp, path)


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {"files": {}, "runs": []}
        if path.exists():
            self.data = json.loads(path.read_text())

    def file_entry(self, key: str) -> dict | None:
        return self.data["files"].get(key)

    def set_file(self, key: str, entry: dict) -> None:
        self.data["files"][key] = entry

    def add_run(self, summary: dict, keep: int = 20) -> None:
        self.data["runs"] = (self.data["runs"] + [summary])[-keep:]

    def save(self) -> None:
        atomic_write(self.path, json.dumps(self.data, indent=2, sort_keys=True))
