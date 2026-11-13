#!/usr/bin/env bash
# Run every local model on both eval sets, one llama-server at a time, then build the report.
# Needs llama-server on PATH (brew install llama.cpp) and HF_USER in .env for the fine-tuned repos.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
MODELS=${MODELS:-"base-q4 ft-q4 ft-q8 ft-f16 base-f16"}

gguf_of() {  # read the -hf spec out of configs/eval.yaml
  MODEL="$1" uv run python -c "
import os, sys
from text2sql.eval.run import load_config
print(load_config('configs/eval.yaml')['models'][os.environ['MODEL']]['gguf'])"
}

for m in $MODELS; do
  echo "== $m"
  case $m in ft-*) alias=finetuned; PORT=8082;; *) alias=base; PORT=8081;; esac  # ports match eval.yaml
  llama-server -hf "$(gguf_of "$m")" --alias "$alias" \
    --port $PORT -c 8192 -np 1 -t 4 >"runs/server_$m.log" 2>&1 &
  pid=$!
  trap 'kill $pid 2>/dev/null || true' EXIT
  for _ in $(seq 1 600); do curl -sf "localhost:$PORT/health" >/dev/null && break; sleep 2; done
  for s in chinook gretel_heldout; do
    uv run python -m text2sql.eval.run --model "$m" --set "$s" || true
  done
  kill $pid; wait $pid 2>/dev/null || true
  trap - EXIT
done
uv run python -m text2sql.eval.compare
