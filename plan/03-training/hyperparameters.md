# Hyperparameters (`configs/train.yaml`) and the reason for each

| Param | Value | Why |
|---|---|---|
| base | `unsloth/Qwen2.5-Coder-1.5B-Instruct-bnb-4bit` | pre-quantized NF4 = QLoRA, fast to load. Decision D2 |
| max_seq_length | 2048 | augmented prompts go up to about 1,800 tokens; Chinook is 1,339 |
| LoRA r / alpha / dropout | 16 / 32 / 0 | r=16 is the standard capacity for a narrow task; alpha = 2r. Unsloth is optimized for dropout 0 |
| target modules | q,k,v,o,gate,up,down | all linear layers, the QLoRA-paper default; better than attention-only |
| epochs | 1 | about 9.5k examples; synthetic data with repeated templates overfits quickly. Watch eval loss |
| per-device batch / grad-accum | 8 / 2 → effective 16 | fits T4 memory at 2048 with gradient checkpointing. If OOM: 4/4 |
| learning rate | 2e-4, cosine, warmup_ratio 0.03 | the standard LoRA LR; cosine decay for a single epoch |
| optimizer | `adamw_8bit` | memory |
| weight decay | 0.01 | |
| precision | `fp16=True, bf16=False` | **T4 has no bf16.** Using bf16 on a T4 is a common mistake |
| packing | False | keeps the per-example response masking simple and correct. A throughput loss we can afford at this size |
| eval | `eval_strategy="steps", eval_steps=100` on the 300-row val | train vs val loss curve = the overfitting evidence |
| save | `save_steps=200, save_total_limit=2, push_to_hub=True, hub_strategy="checkpoint"` | survives Colab disconnects |
| logging | `logging_steps=10, report_to="wandb"` | |
| seed | 3407 | reproducibility (Unsloth's default) |

## Time estimate (unverified until the cell-10 probe)
About 9.5k examples × about 350 tokens average (with augmentation), about 3.3M tokens. One epoch is about 600 steps at an effective batch of 16. On a T4 with Unsloth at 1.5B, expect about 2–4 s/step, i.e. **about 20–40 min**. The cell-10 probe replaces this guess with a measurement. Rule: **if the projection is over 50 min, set `max_steps` to fit 45 min** and note it in the README.

## What "training went right" looks like
- Train loss drops quickly in the first 50–100 steps (format learned), then slowly.
- Eval loss follows train loss and flattens. If eval loss **rises** while train loss falls → overfitting → use the checkpoint with the lowest eval loss (`load_best_model_at_end=True, metric_for_best_model="eval_loss"`).
- The cell-12 val execution accuracy beats the base model's on the same 300 items.
