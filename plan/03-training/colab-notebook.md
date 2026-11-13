# `notebooks/train_qlora_colab.ipynb`: cell-by-cell spec

**The agent writes this notebook to this spec; you run it on Colab** and commit it with outputs. Read every cell before you run it: it's the part you'll be asked to explain line by line. Runtime: Colab → T4 GPU (Kaggle T4 as a backup).

| # | Cell | Key content | Check before moving on |
|---|---|---|---|
| 0 | Runtime check | `!nvidia-smi`; assert "T4" in the name; print torch/CUDA versions | T4, about 15 GB free |
| 1 | Install | `%%capture` then `!pip install unsloth` (Unsloth's current Colab install line). Then `!pip install wandb`. Print `pip freeze \| grep -E "unsloth\|trl\|transformers\|peft\|bitsandbytes\|torch"` | versions printed (they go into the W&B config) |
| 2 | Secrets | `from google.colab import userdata`; `HF_TOKEN`, `WANDB_API_KEY` → env; `huggingface_hub.login` | `whoami` returns your user |
| 3 | Config | a dict mirroring `configs/train.yaml` (see hyperparameters.md) + `DATASET_REPO`, `DATASET_REVISION`, `OUT_REPO_LORA`, `OUT_REPO_GGUF`, `GIT_SHA` | printed |
| 4 | Load model | `FastLanguageModel.from_pretrained("unsloth/Qwen2.5-Coder-1.5B-Instruct-bnb-4bit", max_seq_length=2048, dtype=None, load_in_4bit=True)` | memory about 1.5 GB |
| 5 | LoRA | `FastLanguageModel.get_peft_model(model, r=16, lora_alpha=32, lora_dropout=0, target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"], bias="none", use_gradient_checkpointing="unsloth", random_state=3407)` | `model.print_trainable_parameters()`: about 18M trainable, about 1.2% of the model. **Write this number in the README** |
| 6 | Data | `load_dataset(DATASET_REPO, revision=…)`. Map `text = tokenizer.apply_chat_template(messages, tokenize=False)`. Print one rendered example in full. Assert max tokens ≤ 2048 | the rendered text has our system prompt, then the schema, then `<\|im_start\|>assistant\n<SQL><\|im_end\|>` |
| 7 | **Baseline sanity** | `FastLanguageModel.for_inference(model)`; generate for 3 val items (greedy). Shows the "before" in the notebook | outputs look like SQL |
| 8 | Trainer | `SFTTrainer(model=model, processing_class=tokenizer, train_dataset=…, eval_dataset=val, args=SFTConfig(...))`, with args from hyperparameters.md | constructs without warnings about the text field |
| 9 | Mask prompt tokens | `trainer = train_on_responses_only(trainer, instruction_part="<\|im_start\|>user\n", response_part="<\|im_start\|>assistant\n")`. **Verify:** decode `labels != -100` for one example; it must equal the SQL + `<\|im_end\|>` exactly | printed masked target is correct |
| 10 | Throughput probe | `trainer.train()` with `max_steps=20` in a separate config copy → measure s/step → project the full-epoch time. If it's over 50 min, lower the sample to fit (set `max_steps`) | projected time is written in a markdown cell |
| 11 | Train | full run; `hub_strategy="checkpoint"` pushes checkpoints to the Hub every `save_steps`. On a disconnect: `trainer.train(resume_from_checkpoint=True)` after pulling the last checkpoint | the W&B run shows train and eval loss going down; eval loss not rising (overfitting check) |
| 12 | **Quick proof in the notebook** | greedy-generate the 300 val items in batches, execute in SQLite (rebuild each database from `context_sqlite`), compute execution accuracy for **this model vs the cell 7 base outputs** on the same 300 | numbers printed. This is the early go/no-go before the GGUF export |
| 13 | Save adapter | `model.push_to_hub(OUT_REPO_LORA)` + `tokenizer.push_to_hub(...)` + model card (base model, dataset, hyperparameters, W&B link, eval summary) | repo visible |
| 14 | Export GGUF | `model.push_to_hub_gguf(OUT_REPO_GGUF, tokenizer, quantization_method=["q4_k_m","q8_0","f16"], token=HF_TOKEN)`. It compiles llama.cpp, which takes about 10 min. **Fallback:** `scripts/export_gguf_local.sh` on the Mac (see export.md) | the 3 GGUF files are on the Hub; download Q4 on the Mac: `llama-server -hf <repo>:Q4_K_M` answers |
| 15 | Finish | `wandb.finish()`; print all links | links go into the README |

Repo names: `HF_USER/text2sql-qwen2.5-coder-1.5b-lora`, `HF_USER/text2sql-qwen2.5-coder-1.5b-GGUF`, dataset `HF_USER/text2sql-sqlite-clean`.
