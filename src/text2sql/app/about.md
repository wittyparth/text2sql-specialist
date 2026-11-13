## What this is
- A 1.5B-parameter model (Qwen2.5-Coder) fine-tuned with QLoRA to write **SQLite** queries, next to the unmodified base model.
- Training data comes from an ETL pipeline that **runs every example in SQLite**: rows that don't execute are repaired with sqlglot or dropped.
- Both models see exactly the same prompt, and every answer is run read-only on the database you picked.
- When you choose an example question, the app also runs the reference SQL and compares *results*, the same rule the evaluation uses.
- Everything runs on CPU; no GPU is involved.

## Run it yourself
```
docker compose up        # anywhere Docker runs
./run.sh                 # picks Ollama, llama.cpp or Docker for you
```

First answers after a cold start are slower while the prompt cache fills.
