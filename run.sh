#!/usr/bin/env bash
# One-step local run. Picks the best backend it finds: Ollama, then llama.cpp, then Docker.
#   ./run.sh            auto
#   ./run.sh --docker   force the all-Docker CPU path
#   ./run.sh --ollama   force Ollama
set -uo pipefail
cd "$(dirname "$0")"
[ -f .env ] && { set -a; . ./.env; set +a; }
HF_USER=${HF_USER:-parthasaradhi789}
PORT=${APP_PORT:-7860}
MODE=auto
for a in "$@"; do
  case $a in
    --docker) MODE=docker ;; --ollama) MODE=ollama ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
done

PIDS=()
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
cleanup() { for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done; }
trap cleanup EXIT INT TERM

have() { command -v "$1" >/dev/null 2>&1; }
up() { curl -sf --max-time 2 "$1" >/dev/null 2>&1; }
wait_for() {  # url, seconds
  for _ in $(seq 1 "$2"); do up "$1" && return 0; sleep 1; done
  return 1
}

if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use. Stop whatever is using it, or run with APP_PORT=<other port>."
  exit 1
fi

pick_mode() {
  [ "$MODE" != auto ] && return
  if have ollama; then MODE=ollama
  elif have llama-server; then MODE=llamacpp
  elif have docker; then MODE=docker
  else
    cat <<MSG
No backend found. Install one of:
  Ollama     https://ollama.com/download      (fastest on a Mac, uses the GPU)
  llama.cpp  brew install llama.cpp
  Docker     https://www.docker.com/products/docker-desktop
MSG
    exit 1
  fi
}

start_ollama() {
  have ollama || { echo "ollama is not installed"; exit 1; }
  if ! up http://127.0.0.1:11434/api/tags; then
    say "starting ollama serve (context 8192)"
    OLLAMA_CONTEXT_LENGTH=8192 ollama serve >/dev/null 2>&1 &
    PIDS+=($!)
    wait_for http://127.0.0.1:11434/api/tags 30 || { echo "ollama did not start"; exit 1; }
  fi
  make_model t2s-base ollama/base.Modelfile
  tmp=$(mktemp); sed "s/__HF_USER__/$HF_USER/" ollama/ft.Modelfile > "$tmp"
  make_model t2s-ft "$tmp" || echo "warning: couldn't set up the fine-tuned model; its column will say unavailable"
  export LLM_BASE_URL=http://127.0.0.1:11434/v1 LLM_FT_URL=http://127.0.0.1:11434/v1
  export LLM_BASE_MODEL=t2s-base LLM_FT_MODEL=t2s-ft
}

make_model() {  # name, modelfile; skipped if it already exists
  if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$1:latest"; then
    say "$1 already exists"
  else
    say "creating $1 (downloads the model the first time)"
    ollama create "$1" -f "$2" || return 1
  fi
}

start_llamacpp() {
  say "starting two llama-server processes (8081 base, 8082 fine-tuned)"
  llama-server -hf Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF:Q4_K_M --alias base --port 8081 \
    -c 8192 -np 4 -t 4 >/dev/null 2>&1 &
  PIDS+=($!)
  llama-server -hf "$HF_USER/text2sql-qwen2.5-coder-1.5b-GGUF:Q4_K_M" --alias finetuned --port 8082 \
    -c 8192 -np 4 -t 4 >/dev/null 2>&1 &
  PIDS+=($!)
  wait_for http://127.0.0.1:8081/health 300 || { echo "base server did not start"; exit 1; }
  wait_for http://127.0.0.1:8082/health 300 || echo "warning: fine-tuned server not up; its column will say unavailable"
  export LLM_BASE_URL=http://127.0.0.1:8081/v1 LLM_FT_URL=http://127.0.0.1:8082/v1
  export LLM_BASE_MODEL=base LLM_FT_MODEL=finetuned
}

run_app_native() {
  if have uv; then
    say "starting the app with uv"
    uv run --group app python -m text2sql.app.main &
    PIDS+=($!)
  elif have docker; then
    say "starting the app in Docker (talking to the models on this machine)"
    [ "$MODE" = llamacpp ] && export LLM_BASE_URL=http://host.docker.internal:8081/v1 \
                                     LLM_FT_URL=http://host.docker.internal:8082/v1
    [ "$MODE" = ollama ] && export LLM_BASE_URL=http://host.docker.internal:11434/v1 \
                                  LLM_FT_URL=http://host.docker.internal:11434/v1
    docker compose --profile app-only up --build app-only &
    PIDS+=($!)
  else
    echo "Need uv to run the app: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1
  fi
}

pick_mode
say "backend: $MODE"
case $MODE in
  ollama)   start_ollama;   run_app_native ;;
  llamacpp) start_llamacpp; run_app_native ;;
  docker)
    have docker || { echo "docker is not installed"; exit 1; }
    say "docker compose up (CPU only; the first start downloads about 2 GB of models)"
    docker compose up -d --build || exit 1
    trap - EXIT   # leave the containers running; stop them with: docker compose down
    ;;
esac

if wait_for "http://127.0.0.1:$PORT" 600; then
  say "Open http://localhost:$PORT"
  { have open && open "http://localhost:$PORT"; } || { have xdg-open && xdg-open "http://localhost:$PORT"; } || true
  [ "$MODE" = docker ] && exit 0
  wait
else
  echo "The app did not come up on port $PORT."; exit 1
fi
