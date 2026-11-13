# Run locally in one step: `./run.sh` (Ollama, llama.cpp or Docker; picked automatically)

## Why this works with any backend
The app only talks to an **OpenAI-compatible `/v1/chat/completions`** endpoint. llama.cpp's `llama-server`, **Ollama**, LM Studio, `mlx_lm.server` and OpenRouter all expose one. A backend is just two env vars per model:

| Env var | llama-server (compose) | Ollama (native) |
|---|---|---|
| `LLM_BASE_URL` / `LLM_FT_URL` | `http://llm-base:8080/v1` / `http://llm-ft:8080/v1` | `http://localhost:11434/v1` (both) |
| `LLM_BASE_MODEL` / `LLM_FT_MODEL` | `base` / `finetuned` (llama-server `--alias`) | `t2s-base` / `t2s-ft` (Ollama model names) |

The app and eval client must send `model=<name>` on every request. llama-server ignores it; Ollama and OpenRouter need it.

## Serving options compared (why each one exists in this repo)
| Option | Hardware | Speed on a Mac | Setup for a stranger | Role here |
|---|---|---|---|---|
| **Ollama, native** | Metal GPU on Mac / CUDA / CPU | fastest (Metal) | `brew install ollama` (or the app installer) | **the recommended one-step local run on a Mac** |
| llama.cpp `llama-server`, native | Metal / CUDA / CPU | fastest (Metal) | `brew install llama.cpp` | evals (exact GGUF control, timings, prompt cache) |
| llama.cpp server, **Docker** | CPU only (Docker on a Mac can't use Metal) | OK: warm 1.3 s on 2 CPUs | only Docker | **zero-install path for anyone**, Linux and Windows too |
| HF Space | 2 vCPU | slower | none (a URL) | the public demo, if the account allows it (T6.0) |
| vLLM / TGI | NVIDIA GPU | n/a | heavy | not used: GPU cost. Named as the scale-up path |
| transformers.js / WebLLM in the browser | the user's GPU | varies | none | not used: model conversion risk in one day |

## Ollama specifics (from Ollama's docs, 2026-11-13)
- **Default context is 4,096 tokens, and the OpenAI-compatible API cannot change it.** The Chinook prompt is 1,339 tokens + 256 output, which fits one request, but the plan sets **8,192** for headroom. That's done by **Modelfiles** (`PARAMETER num_ctx 8192`), which work no matter how the user started Ollama, plus `OLLAMA_CONTEXT_LENGTH=8192` when `run.sh` starts the server itself.
- Modelfiles committed in `ollama/`:
  ```
  # ollama/base.Modelfile
  FROM hf.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF:Q4_K_M
  PARAMETER num_ctx 8192
  PARAMETER temperature 0
  # ollama/ft.Modelfile
  FROM hf.co/${HF_USER}/text2sql-qwen2.5-coder-1.5b-GGUF:Q4_K_M
  PARAMETER num_ctx 8192
  PARAMETER temperature 0
  ```
  `ollama create t2s-base -f ollama/base.Modelfile` (and the same for `t2s-ft`). If `FROM hf.co/...` isn't supported by the user's Ollama version, the fallback is `hf download` of the `.gguf` and `FROM ./file.gguf` (documented in Ollama's import docs).
- **Chat template:** Ollama derives the template from the GGUF metadata. Verify (acceptance below) that the system prompt is honoured and the output stops at `<|im_end|>`. If not, add an explicit ChatML `TEMPLATE` to the Modelfile.
- Both models stay loaded together (about 1.1 GB each).

## `run.sh` behaviour (one command, prints every choice it makes)
```
./run.sh            # auto
./run.sh --docker   # force the all-Docker CPU path
./run.sh --ollama   # force Ollama
```
1. **Detect:**
   - `ollama` present → **Ollama mode**. Start `ollama serve` with `OLLAMA_CONTEXT_LENGTH=8192` if `:11434` isn't answering, then `ollama create` both models (idempotent: skipped if they exist with the same Modelfile digest).
   - else `llama-server` present → **native llama.cpp mode**: start two servers on 8081/8082 with `-c 8192 -np 4`.
   - else `docker` present → `docker compose up -d` and you're done.
   - else → print the install options and exit 1.
2. **Run the app (native modes):**
   - `uv` present → `uv run python -m text2sql.app.main`.
   - else Docker present → `docker compose --profile app-only up app`, with the URLs pointing at `host.docker.internal`.
   - else → tell the user to install `uv` (one line).
3. Wait for `/health` (llama-server) or `GET /api/tags` (Ollama), run the warmup, then print `Open http://localhost:7860` and open it with `open`/`xdg-open`.
4. Ctrl-C → stop only what `run.sh` started.

Add the Makefile alias `make run` → `./run.sh`.

## Verified on 2026-11-13
`ollama pull hf.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF:Q4_K_M` works. The Modelfile above (+ `ollama create`) gives **byte-identical SQL to llama-server on 100/100 Chinook items** (one request at a time). The GGUF's chat template is honoured.

## Acceptance (T4.4)
- [ ] Mac with Ollama: `./run.sh` → UI works; a Chinook example takes under 1.5 s per model (Metal)
- [ ] Mac with only Docker: `./run.sh` → falls through to compose; the UI works
- [ ] Ollama model output for 10 Chinook items is **identical** to llama-server output for the same GGUF at temperature 0 (or differences are explained). This proves the template and system prompt are honoured
- [ ] Running `./run.sh` twice doesn't duplicate servers or models
