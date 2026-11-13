# Experiment tracking + export

## W&B run (public)
- Project: `text2sql-specialist`. Run name: `qwen2.5c-1.5b-qlora-r16-{dataset_rev[:7]}`.
- `wandb.config` gets: every hyperparameter, dataset repo + revision, the git SHA of this repo, library versions (cell 1), the T4 GPU name, and the trainable parameter count.
- Logged: train/eval loss, learning rate, grad norm, tokens/s. At the end: val execution accuracy (base vs fine-tuned) as a summary metric and a `wandb.Table` of 20 val predictions (question, gold, base, fine-tuned, match).
- **Set the project to public** and link it in the README.

## Artifacts
| Artifact | Where | Used by |
|---|---|---|
| LoRA adapter (about 70 MB) | `HF_USER/text2sql-qwen2.5-coder-1.5b-lora` | reproducibility, future DPO |
| GGUF Q4_K_M / Q8_0 / F16 | `HF_USER/text2sql-qwen2.5-coder-1.5b-GGUF` | eval (all three), app/Docker/Space (Q4_K_M) |
| Model card | both repos | base model, data, method, eval table, limitations, license (Apache-2.0, matching Qwen2.5-Coder) |

## GGUF export fallback (`scripts/export_gguf_local.sh`, Mac)
If the Unsloth GGUF export fails in Colab:
1. In Colab: `model.push_to_hub_merged(REPO_MERGED, tokenizer, save_method="merged_16bit")` (about 3 GB).
2. On the Mac:
   - `hf download REPO_MERGED --local-dir merged`
   - `git clone --depth 1 https://github.com/ggml-org/llama.cpp`
   - `uv run --with -r llama.cpp/requirements/requirements-convert_hf_to_gguf.txt python llama.cpp/convert_hf_to_gguf.py merged --outtype f16 --outfile ft-f16.gguf`
   - `llama-quantize ft-f16.gguf ft-q4_k_m.gguf Q4_K_M` (and the same for Q8_0). `llama-quantize` ships with the brew llama.cpp.
3. `hf upload REPO_GGUF ft-*.gguf`.

**Check after either path:** `llama-server -hf REPO_GGUF:Q4_K_M` answers a Chinook question and the chat template is embedded. The output must end cleanly at `<|im_end|>` with no rambling. If it rambles, the EOS token or template wasn't carried over; fix it with `--chat-template chatml`.
