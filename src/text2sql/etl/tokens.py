"""Token budget helpers. The real counter uses the Qwen tokenizer; tests inject a cheap one."""

from typing import Protocol

from ..prompt import build_messages
from .records import Record


class TokenCounter(Protocol):
    def count_many(self, texts: list[str]) -> list[int]: ...


def render_chatml(messages: list[dict]) -> str:
    """Qwen2.5 chat template for a full conversation with an explicit system turn."""
    return "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)


def record_text(rec: Record) -> str:
    return render_chatml(build_messages(rec.schema_canonical, rec.question, rec.sql))


class QwenCounter:
    def __init__(self, name: str):
        from tokenizers import Tokenizer

        self._tok = Tokenizer.from_pretrained(name)

    def count_many(self, texts: list[str]) -> list[int]:
        return [len(e.ids) for e in self._tok.encode_batch(texts)]


class CharCounter:
    """Offline stand-in: about 3.5 characters per token for English + SQL."""

    def count_many(self, texts: list[str]) -> list[int]:
        return [max(1, len(t) * 2 // 7) for t in texts]


def fill_token_counts(records: list[Record], counter: TokenCounter) -> int:
    """Count tokens for kept records that don't have a count yet. Returns how many were counted."""
    todo = [r for r in records if r.status == "kept" and r.n_tokens == 0]
    for rec, n in zip(todo, counter.count_many([record_text(r) for r in todo]), strict=True):
        rec.n_tokens = n
    return len(todo)
