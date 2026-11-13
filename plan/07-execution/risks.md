# Risks and fallbacks

| # | Risk | Likelihood | Impact | Early signal | Mitigation / fallback |
|---|---|---|---|---|---|
| R1 | Colab disconnects mid-training | medium | high | runtime banner | `hub_strategy="checkpoint"` every 200 steps; resume; Kaggle T4 (30 h/week) as the alternate GPU |
| R2 | Free Colab gives no T4 | low–medium | high | cell 0 | Kaggle notebook (same code); reduce to 6k examples |
| R3 | Unsloth/TRL version breakage (APIs moved: `processing_class` vs `tokenizer`, `max_length` vs `max_seq_length`) | medium | medium | cell 8 errors | follow Unsloth's current Qwen2.5 notebook signature for the installed version; log the versions |
| R4 | GGUF export fails in Colab | medium | medium | cell 14 | push the merged 16-bit model → convert and quantize on the Mac (`scripts/export_gguf_local.sh`, brew `llama-quantize` is available) |
| R5 | Fine-tuned model doesn't stop (rambles past the SQL) | low–medium | high | cell 12 outputs | check `<\|im_end\|>` in the targets; server `--chat-template chatml`; stop sequence `<\|im_end\|>` in requests |
| R6 | Fine-tuned ≤ base | low | high | G3 | the G3 decision rules in timeline.md; honest reporting |
| R7 | Worse on long schemas (Chinook) after short-schema training | **medium** | medium | Chinook EX < 59% (deterministic base) | distractor augmentation (stage 08) is the preventive fix; report it as a finding if it happens anyway |
| R8 | HF Space too slow on 2 vCPU with two models | medium | medium | T6.2 latency | prompt cache + warmup (measured 12.4 s → 1.3 s); `APP_SEQUENTIAL=1`; worst case: Space shows the fine-tuned model only, and Docker gives the side-by-side |
| R9 | Space Docker build fails (uv Python, permissions as uid 1000) | medium | medium | build logs | test the exact Dockerfile locally first (T6.1); apt `python3-venv` fallback |
| R10 | llama-server context overflow | **observed** | high | HTTP 500 | `-c 8192 -np 4`; the rule is documented |
| R11 | llama.cpp image tag drift changes behavior | low | low | — | pinned by digest (`sha256:2103d1f4…`, build b12316) |
| R12 | Eval set ambiguity inflates or deflates scores | medium | medium | audit | normalization rules + the human spot-check + the gold-noise audit, all reported |
| R13 | Secrets leak into git | low | high | — | `.env` gitignored; tokens only in Colab secrets; the grep check in the submission checklist |
| R15 | **Free Docker Spaces may require PRO now** (docs vs mid-2026 community reports conflict) | **medium–high** | medium | T6.0 check | PRO about $9/month, or Mac + `docker compose` + Cloudflare quick tunnel; `docker compose up` is always available (see hf-space.md) |
| R14 | Time overrun | **high** | high | gates slip | the cut order in timeline.md; the never-cut list |
