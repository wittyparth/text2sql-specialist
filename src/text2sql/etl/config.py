from pathlib import Path

import yaml
from pydantic import BaseModel


class SourceCfg(BaseModel):
    kind: str  # hf | url | local
    files: list[str]
    repo: str | None = None
    revision: str = "local"
    url: str | None = None
    sha256: str | None = None


class PathsCfg(BaseModel):
    raw: Path = Path("data/raw")
    interim: Path = Path("data/interim")
    processed: Path = Path("data/processed")
    state: Path = Path("data/state")
    eval: Path = Path("data/eval")
    reports: Path = Path("reports")


class ValidateCfg(BaseModel):
    timeout_s: float = 2.0
    max_rows: int = 1000
    workers: int = 1


class FiltersCfg(BaseModel):
    question_min_chars: int = 10
    question_max_chars: int = 500
    sql_max_chars: int = 2000
    token_budget: int = 1800
    tokenizer: str = "Qwen/Qwen2.5-Coder-1.5B-Instruct"


class SplitCfg(BaseModel):
    test_domains: int = 10
    val_domains: int = 5
    eval_size: int = 500
    eval_floor_per_class: int = 25
    val_size: int = 300


class SampleCfg(BaseModel):
    gretel: int = 8000
    sqlcc: int = 1500
    basic_cap: float = 0.30
    class_weights: dict[str, float]


class AugmentCfg(BaseModel):
    rate: float = 0.35
    min_distractors: int = 3
    max_distractors: int = 8
    pool_records: int = 4000


class Config(BaseModel):
    seed: int = 42
    sources: dict[str, SourceCfg]
    paths: PathsCfg = PathsCfg()
    validate_: ValidateCfg = ValidateCfg()
    filters: FiltersCfg = FiltersCfg()
    split: SplitCfg = SplitCfg()
    sample: SampleCfg
    augment: AugmentCfg = AugmentCfg()

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        raw = yaml.safe_load(Path(path).read_text())
        if "validate" in raw:
            raw["validate_"] = raw.pop("validate")
        return cls(**raw)
