from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def chinook_path() -> Path:
    return ROOT / "data" / "demo" / "chinook.sqlite"
