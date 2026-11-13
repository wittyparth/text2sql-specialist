# Docker: anyone can run it on a Mac or Linux with one command

## Goal
`git clone … && docker compose up` gives you the full demo at http://localhost:7860: base vs fine-tuned, running on CPU, with **no GPU, no Python setup and no keys**.

## Facts this design rests on (verified, see `00-context/verified-facts.md`)
- `ghcr.io/ggml-org/llama.cpp:server` is multi-arch (linux/amd64 and **linux/arm64**), so it runs natively on Apple Silicon.
- Docker on a Mac **can't use Metal**, so containers run on CPU. Measured: 1.3 s per warm Chinook request on 2 CPUs; 12.4 s cold.
- `llama-server -hf user/repo:Q4_K_M` downloads from the HF Hub itself, so the model files don't need to be in the image.
- The image runs as root and is Ubuntu 26.04 with `apt-get`, `python3` and `curl`. Pin it by digest.

## `docker-compose.yml` (spec)

```yaml
x-llm: &llm
  image: ghcr.io/ggml-org/llama.cpp:server@sha256:2103d1f4f2e2e223ad80587dcb39fc15a9f912f29ae1fa9fc1193fe8c1aea82f
  volumes: [llm-cache:/root/.cache]   # models downloaded once, survive restarts. Mount all of ~/.cache: the brew build of
                                      # this llama.cpp version stored -hf downloads in ~/.cache/huggingface/hub (verified), not ~/.cache/llama.cpp
  healthcheck: {test: ["CMD", "curl", "-f", "http://localhost:8080/health"], interval: 10s, retries: 30, start_period: 20s}
  restart: unless-stopped

services:
  llm-base:
    <<: *llm
    command: ["-hf", "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF:Q4_K_M", "-c", "8192", "-np", "4", "-t", "${LLM_THREADS:-4}", "--alias", "base"]
  llm-ft:
    <<: *llm
    command: ["-hf", "${HF_USER}/text2sql-qwen2.5-coder-1.5b-GGUF:Q4_K_M", "-c", "8192", "-np", "4", "-t", "${LLM_THREADS:-4}", "--alias", "finetuned"]
  app:
    build: {context: ., dockerfile: docker/app.Dockerfile}
    environment:
      LLM_BASE_URL: http://llm-base:8080/v1
      LLM_FT_URL: http://llm-ft:8080/v1
    ports: ["7860:7860"]
    depends_on: {llm-base: {condition: service_healthy}, llm-ft: {condition: service_healthy}}
  etl:            # docker compose --profile etl run --rm etl
    build: {context: ., dockerfile: docker/app.Dockerfile}
    profiles: [etl]
    command: ["python", "-m", "text2sql.etl.pipeline", "run"]
    volumes: [./data:/app/data, ./reports:/app/reports]
  eval:           # docker compose --profile eval run --rm eval
    build: {context: ., dockerfile: docker/app.Dockerfile}
    profiles: [eval]
    command: ["python", "-m", "text2sql.eval.run", "--config", "configs/eval.yaml"]
    environment: {LLM_BASE_URL: http://llm-base:8080/v1, LLM_FT_URL: http://llm-ft:8080/v1}
    volumes: [./runs:/app/runs, ./reports:/app/reports]
    depends_on: {llm-base: {condition: service_healthy}, llm-ft: {condition: service_healthy}}
volumes: {llm-cache: {}}
```

Notes:
- **Context sizing rule:** `-c ≥ n_parallel × (max_prompt + max_tokens)`. With 4 slots, 1.4k prompts and 256 output tokens, 8192 is enough for the demo's 4 preset databases. A wrong value causes HTTP 500 "Context size has been exceeded", which we hit with `-c 4096 -np 4`.
- **The `HF_USER` default** is set in `.env.example`, so it works without editing anything. The fine-tuned GGUF repo is public.
- **Memory:** about 1.1 GB per Q4 model, so the whole stack needs under 4 GB of RAM.

## `docker/app.Dockerfile` (spec)
- Multi-stage: `python:3.12-slim` + `COPY --from=ghcr.io/astral-sh/uv:<pinned> /uv /bin/uv`.
- `uv sync --frozen --no-dev --group etl --group eval --group app`. Copy `uv.lock` and `pyproject.toml` first so the dependency layer gets cached.
- Copy `src/`, `configs/` and `data/demo/` and `data/eval/` (both small and committed).
- Run as a non-root user, `EXPOSE 7860`, `CMD ["python", "-m", "text2sql.app.main"]`.
- Measured image size: about 750 MB (Gradio, pandas and numpy dominate). Use `--no-cache` on `uv sync` or the uv download cache doubles it.

## `docker/space.Dockerfile` (HF Space, single container, spec)
HF Docker Spaces run **one** container, listen on **port 7860** and run as **uid 1000**.
```
FROM ghcr.io/ggml-org/llama.cpp:server@sha256:2103d1f4…   # Ubuntu 26.04, has /app/llama-server
COPY --from=ghcr.io/astral-sh/uv:<pinned> /uv /bin/uv
RUN useradd -m -u 1000 user
USER user ; WORKDIR /home/user/app
ENV UV_PYTHON_INSTALL_DIR=/home/user/.uv-python  HOME=/home/user
COPY --chown=user pyproject.toml uv.lock ./
RUN uv python install 3.12 && uv sync --frozen --no-dev --group app
COPY --chown=user src configs data/demo data/eval docker/space-entrypoint.sh ./
# Bake both GGUFs into the image → no download at cold start (~2.2 GB extra, fine for Spaces)
RUN /app/llama-server --help >/dev/null && uv run python -c "from huggingface_hub import hf_hub_download as d; d('Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF','qwen2.5-coder-1.5b-instruct-q4_k_m.gguf', local_dir='models'); d('${HF_USER}/text2sql-qwen2.5-coder-1.5b-GGUF','<file>.gguf', local_dir='models')"
ENTRYPOINT ["bash", "space-entrypoint.sh"]
```
`space-entrypoint.sh`:
1. Start `/app/llama-server -m models/base.gguf --port 8081 -c 8192 -np 4 -t 2 --host 127.0.0.1 &`, then the same for the fine-tuned model on port 8082.
2. Poll `/health` on both, with a 120 s timeout.
3. `uv run python -m text2sql.app.warmup` primes each preset database's prompt cache on both servers. Measured effect: 12.4 s cold → 1.3 s warm on 2 CPUs.
4. `exec uv run python -m text2sql.app.main --host 0.0.0.0 --port 7860`.

**Verify before relying on it** (task T6.2):
- `docker build -f docker/space.Dockerfile .` succeeds.
- `docker run --cpus 2 -p 7860:7860 …` serves the UI.
- The warm Chinook request takes under 3 s.

**Fallback if uv-managed Python fails inside the image:** use `apt-get install -y python3-venv` as root before `USER user`.

## Native Mac fast path (documented in the README as an alternative)
`brew install llama.cpp && make serve-native && make app`. This uses Metal (measured 0.4–0.9 s per request). It's the recommended way to run evals locally.
