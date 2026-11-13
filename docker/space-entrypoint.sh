#!/usr/bin/env bash
# Start both model servers inside the container, wait for them, then hand over to the app.
set -euo pipefail

THREADS=${LLM_THREADS:-2}   # a free Space has 2 vCPUs
# -c must be >= slots x (longest prompt + max_tokens); see docs in docker-compose.yml
serve() {  # file alias port
  /app/llama-server -m "models/$1.gguf" --alias "$2" --host 127.0.0.1 --port "$3" \
    -c 8192 -np 2 -t "$THREADS" >"/tmp/llm-$2.log" 2>&1 &
}
serve base base 8081
serve ft finetuned 8082

for port in 8081 8082; do
  for _ in $(seq 1 60); do
    curl -sf "127.0.0.1:$port/health" >/dev/null && break
    sleep 2
  done
  curl -sf "127.0.0.1:$port/health" >/dev/null || { echo "model server on :$port did not start"; exit 1; }
done

export APP_HOST=0.0.0.0 APP_PORT=7860
exec python -m text2sql.app.main
