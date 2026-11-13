import hashlib
import re
from dataclasses import asdict, dataclass, fields

try:
    import sqlglot
except ImportError:  # the app image doesn't ship sqlglot
    sqlglot = None


@dataclass(slots=True)
class Record:
    id: str = ""
    source_row_key: str = ""
    source: str = ""
    source_id: str | None = None
    domain: str = ""
    complexity: str = ""
    complexity_derived: str = ""
    task_type: str = ""
    question: str = ""
    context_raw: str = ""
    context_sqlite: str = ""
    schema_canonical: str = ""
    n_tables: int = 0
    sql_raw: str = ""
    sql: str = ""
    repaired: bool = False
    repair_dialect: str | None = None
    validation_level: str = ""
    result_rows: int | None = None
    result_empty: bool = False
    order_matters: bool = False
    time_dependent: bool = False
    n_tokens: int = 0
    status: str = "kept"
    drop_reason: str | None = None
    drop_detail: str | None = None
    split: str | None = None
    augmented: bool = False
    sampled: bool = False
    run_id: str = ""

    def drop(self, reason: str, detail: str | None = None) -> "Record":
        self.status = "dropped"
        self.drop_reason = reason
        self.drop_detail = (detail or "")[:300] or None
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Record":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def norm_text(text: str) -> str:
    """Lowercase, collapse whitespace, drop trailing punctuation. For questions."""
    return re.sub(r"\s+", " ", text.lower()).strip().rstrip(";.?! ")


def norm_sql(sql: str) -> str:
    if sqlglot is not None:
        try:
            return sqlglot.parse_one(sql, read="sqlite").sql(normalize=True, pretty=False)
        except sqlglot.errors.SqlglotError:
            pass
    return norm_text(sql)


def make_id(question: str, schema: str, sql: str) -> str:
    key = "\x1f".join([norm_text(question), schema, norm_sql(sql)])
    return hashlib.sha256(key.encode()).hexdigest()[:16]
