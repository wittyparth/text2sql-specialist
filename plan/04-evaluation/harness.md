# Eval harness design (`src/text2sql/eval/`)

## Principle: evaluate the artifact we ship, through the same interface the app uses
Every model is reached over an **OpenAI-compatible `/v1/chat/completions`** endpoint (`eval/client.py`):
- local GGUFs via `llama-server` (Metal on the Mac for speed, or the Docker CPU containers)
- optional frontier baseline via OpenRouter (`https://openrouter.ai/api/v1`, key from `.env`)

So the base model, the fine-tuned model, every quantization and an API model all go through **identical** prompt building, extraction, execution and scoring code.

## `configs/eval.yaml`
```yaml
generation: {temperature: 0, max_tokens: 256, seed: 0}
parallel: 1                      # one request at a time = deterministic (4 slots flip ~5% of greedy outputs; verified-facts.md)
sets:
  gretel_heldout: data/eval/gretel_heldout_eval.jsonl   # 500, rebuild DB per item from context_sqlite
  chinook:        data/eval/chinook_eval.jsonl          # 100, data/demo/chinook.sqlite read-only
models:
  base-q4:  {url: http://127.0.0.1:8081/v1, gguf: Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF:Q4_K_M}
  base-f16: {url: http://127.0.0.1:8081/v1, gguf: Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF:F16}
  ft-q4:    {url: http://127.0.0.1:8082/v1, gguf: ${HF_USER}/text2sql-qwen2.5-coder-1.5b-GGUF:Q4_K_M}
  ft-q8:    {url: http://127.0.0.1:8082/v1, gguf: ${HF_USER}/text2sql-qwen2.5-coder-1.5b-GGUF:Q8_0}
  ft-f16:   {url: http://127.0.0.1:8082/v1, gguf: ${HF_USER}/text2sql-qwen2.5-coder-1.5b-GGUF:F16}
  frontier: {url: https://openrouter.ai/api/v1, model: <chosen at run time>, optional: true}
```
`make eval-all` restarts the right llama-server with the right GGUF for each model. One model runs at a time on Metal, so latency numbers don't interfere with each other.

## Run outputs (`runs/{timestamp}_{model}_{set}/`)
- `predictions.jsonl`: id, raw output, extracted SQL, ok, error_class, error, pred_rows (first 20), latency, prompt/completion tokens
- `summary.json`: EX, EX-strict, valid rate, error breakdown, per difficulty with n, latency p50/p95, CI
- `config.json`: the model, endpoint, GGUF file, generation params, git SHA, eval-file sha256 (proves the frozen set wasn't changed)

## `eval/compare.py` → `reports/eval_results.md` + `.json` + figures
- Main table, paired comparisons, per-difficulty chart, quantization chart, and error-class shift (base → fine-tuned).
- 10 qualitative examples where base was wrong and fine-tuned was right, and 5 where fine-tuned was wrong and base was right. Show both directions; it's more credible.

## Measured cost of running it
On the M5 with Metal, one request at a time: about 0.3–0.5 s per Gretel item and about 1–2 s per Chinook item, i.e. about 3–4 min per (model × set). **The full matrix (5 local models × 2 sets) takes about 35 min**, plus F16 being about 2× slower. Start it as soon as the GGUF exists.

## Already-written prototype
`scripts/prototypes/base_probe.py` and `chinook_probe.py` implement this loop in about 60 lines and produced the baselines. The harness is their productionized version with config, retries, JSON outputs and tests.
