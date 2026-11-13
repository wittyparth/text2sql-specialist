"""Publish the demo to a Hugging Face Docker Space.

    python -m scripts.deploy_space --dry-run     # assemble the folder and list it
    python -m scripts.deploy_space               # create/update HF_USER/text2sql-specialist

Needs HF_TOKEN and HF_USER in .env. Publishing is public, so run it on purpose.
"""

import argparse
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPACE_NAME = "text2sql-specialist"
# what the image needs, nothing else (no raw/interim data, notebooks, tests, runs)
INCLUDE = [
    "pyproject.toml",
    "uv.lock",
    "src",
    "configs",
    "data/demo",
    "data/eval",
    "reports",
    "docs",
]

HEADER = """---
title: Text-to-SQL Specialist
emoji: 🗄️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
---

"""


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def assemble(dest: Path) -> list[str]:
    for rel in INCLUDE:
        src, target = ROOT / rel, dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, target)
    shutil.copy2(ROOT / "docker/space.Dockerfile", dest / "Dockerfile")
    shutil.copy2(ROOT / "docker/space-entrypoint.sh", dest / "space-entrypoint.sh")
    (dest / "README.md").write_text(HEADER + (ROOT / "README.md").read_text())
    return sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_env()

    with tempfile.TemporaryDirectory() as tmp:
        files = assemble(Path(tmp))
        print(f"{len(files)} files, e.g. {files[:6]}")
        if args.dry_run:
            return
        from huggingface_hub import HfApi

        user = os.environ["HF_USER"]
        repo_id = f"{user}/{SPACE_NAME}"
        api = HfApi(token=os.environ["HF_TOKEN"])
        api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
        api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=tmp)
        print(f"uploaded: https://huggingface.co/spaces/{repo_id}")


if __name__ == "__main__":
    main()
