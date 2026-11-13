# Talking points (for the follow-up conversation)

## Message to send with the links (draft; edit in your voice)
> Hi [name], here's the project: **[demo link]** (try the example questions; base vs my fine-tuned model side by side, running on CPU).
> I built an ETL pipeline over three text-to-SQL sources. It validates every example by running it in SQLite (about 24% of a popular public dataset didn't run). Then I QLoRA-fine-tuned Qwen2.5-Coder-1.5B on a free T4: execution accuracy went from X% to Y% on unseen domains and from 59% to Z% on a real 11-table database. Repo with the full pipeline, eval and Docker setup: **[GitHub]**.

## "Have you set up ETL pipelines?" — answer with this project
- **Extract:** pinned revisions, retries, checksums, three formats (Parquet, JSON, a SQLite DB).
- **Transform:**
  - map everything to one record format and one canonical schema format
  - repair dialects with sqlglot
  - **validate by execution** and record why each dropped row was dropped
  - dedup in 3 passes, plus a leakage guard
- **Load:** Parquet as the source of truth; JSONL in chat format for training; HF Hub with a dataset card.
- **Operations:** idempotent (content-hash ids, atomic writes), incremental (manifest, `--limit` demo), observable (per-stage funnel report), tested in CI.
- **At scale I'd add:**
  - orchestration (Dagster or Airflow) for scheduled sources
  - DuckDB or Spark instead of in-memory Python
  - MinHash near-dedup
  - data contracts (pydantic/pandera) and alerting on funnel drift

## Fine-tuning concepts, ready to explain from your own run
- **SFT vs pretraining.**
- **Full fine-tuning vs PEFT; LoRA:** a low-rank update ΔW = BA. r=16, alpha=32. About 18M trainable parameters, 1.2% of the model.
- **QLoRA:** a frozen NF4 4-bit base model, LoRA adapters in higher precision, paged 8-bit optimizers.
- Why **fp16, not bf16, on a T4**. Why the **loss is computed only on the response tokens**. **Overfitting** read from the eval-loss curve.
- **Quantization:** what you measured F16 → Q8 → Q4 costing in accuracy (real numbers). GGUF (llama.cpp) vs GPTQ/AWQ (GPU kernels).
- **DPO** (the likely "dio"): preference pairs, no reward model, β. Your execution-feedback DPO design. vs **RLHF/PPO** and **GRPO with verifiable rewards**.
- **When to fine-tune vs RAG vs prompting.**
  - RAG is for knowledge that changes.
  - Fine-tuning is for **behavior and format**: SQLite dialect, schema linking, output discipline. Here it also gives cost and latency at 1.5B.
  - Prompting a frontier model is the baseline you compare against (the optional OpenRouter row).
- **Model landscape:**
  - open-weight vs closed
  - base vs instruct
  - dense vs **MoE** (total vs active parameters; Qwen3.x MoE models)
  - why you picked a dense 1.5B coder over the newer Qwen3.5 small models (hybrid Mamba, T4 friction, Unsloth's QLoRA warning)

## The two "trend" questions he asked
- **System-1 models (e.g. TypeSafe's Jev):**
  - Fast models that return a typed decision with a probability, instead of generating text, for routing, guarding and verification steps in agents.
  - Related to your project: a fine-tuned small model is a cheap, specialized component, and the trade-off between buying one and building one is the same argument.
- **Weight-space editing (MIT CSAIL, Nov 2026):**
  - A frontier model edited about 0.016% of Qwen3.5-0.8B's weights directly, with no gradient descent. Reported MATH-500 went from 7.9% to 48.1%.
  - Critics say it mostly fixed a reasoning-loop bug rather than adding capability.
  - Contrast with fine-tuning: gradients on data vs direct edits. It's interesting for interpretability and model repair, but for production you'd still use SFT/LoRA + evals because they're reproducible and measurable.
