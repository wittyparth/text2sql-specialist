# Serving architecture

```
                 ┌──────────────────────────── same code, three ways to run ────────────────────────────┐
                 │                                                                                         │
 Browser ──► Gradio app (text2sql.app.main, :7860)                                                         │
               │  build_messages(canonical schema, question)   ← prompt.py (shared contract)               │
               │  POST /v1/chat/completions (OpenAI-compatible, httpx, timeout 60 s)                        │
               ├──────────► llm-base : llama-server  Qwen2.5-Coder-1.5B-Instruct Q4_K_M                    │
               └──────────► llm-ft   : llama-server  ours, Q4_K_M                                          │
               │  extract_sql → run_select(read-only SQLite, authorizer, 5 s timeout) → result table       │
               ▼                                                                                           │
            side-by-side SQL + status + result (+ "matches reference" for example questions)               │
                                                                                                           │
  1) docker compose up        : 3 containers (llm-base, llm-ft, app), CPU, Mac/Linux                       │
  2) HF Space (Docker SDK)    : 1 container, 2 llama-server processes + app, free 2 vCPU / 16 GB            │
  3) Native Mac               : brew llama.cpp on Metal + `make app` (fastest; used for evals)              │
                 └─────────────────────────────────────────────────────────────────────────────────────────┘
```

## Performance design (all from measurements)
| Concern | Measurement | Design response |
|---|---|---|
| Long schema prefill on CPU | Chinook cold: 12.4 s on 2 CPUs | **Prompt-prefix caching:** system + schema come first (prompt contract). `-np 4` gives one slot per preset database. `warmup.py` primes every (model × preset database) at startup. Measured warm: **1.3 s** |
| Context overflow | `-c 4096 -np 4` → HTTP 500 | `-c 8192 -np 4` (rule: c ≥ np × (max_prompt + max_tokens)) |
| Two models on 2 vCPUs | not yet measured on the Space hardware | default: run both requests **concurrently**, each server `-t 2`. If the warm p50 on the Space is over 4 s, switch to **sequential, fine-tuned first, streamed into the UI** (config flag `APP_SEQUENTIAL=1`) |
| Space CPUs are slower than the M5 | unknown, expect 2–3× | the README states measured Space latency, not M5 numbers |
| Cold start (Space sleeping) | model download avoided by **baking the GGUFs into the image** | the first page load still waits for container start, about 1 min. The UI shows a "warming up" banner until `/health` and the warmup are done |

## Why not stream tokens
SQL outputs are short (22–47 tokens measured). Streaming adds complexity for little user-visible gain. Show a spinner, then the full SQL. Revisit only if the Space latency is bad.
