# The prompt contract (`src/text2sql/prompt.py`): one definition, used everywhere

If training, eval and the app format prompts even slightly differently, the measured gains are partly fake. So the format lives in exactly one module.

```python
SYSTEM_PROMPT = (
    "You are a SQLite expert. Given a database schema and a question, write one SQLite SELECT "
    "query that answers the question. Output only the SQL query."
)

def build_messages(schema: str, question: str, answer_sql: str | None = None) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Schema:\n{schema}\n\nQuestion: {question}"}]
    if answer_sql is not None:
        msgs.append({"role": "assistant", "content": answer_sql})
    return msgs

def extract_sql(text: str) -> str:
    """Same extractor for base, fine-tuned and API models (fairness)."""
    # 1) if a ``` fenced block exists → take its content (```sql / ```sqlite / bare)
    # 2) strip leading 'SQL:' / 'Answer:' / 'Query:' labels
    # 3) cut at the first ';' that is outside a string literal (sqlglot tokenizer), else whole text
    # 4) strip whitespace; return '' if nothing SQL-like (no SELECT/WITH keyword)
```

## Rules
- **The schema comes before the question**, so the system prompt and schema form a stable prefix. llama-server reuses the cached prefix: measured 12.4 s cold → 1.3 s warm on 2 CPUs. This ordering is a performance decision as well as a format one.
- **Always send the system message.** Without one, Qwen2.5's chat template injects its default "You are Qwen, created by Alibaba Cloud…" system prompt, which would differ between training and serving.
- Assistant target = bare SQL, no trailing `;`, no fences. The chat template appends `<|im_end|>`, so the model learns to stop. Generation uses `temperature=0`, `max_tokens=256`.
- This exact system prompt was used in the baseline probes (62.0% / 62.0%), so the baseline numbers are directly comparable.
