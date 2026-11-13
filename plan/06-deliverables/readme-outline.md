# Final README.md outline (the reviewer reads the first screen; make it count)

**Write sections 1, 4 and 7 in your own words.** The reviewer is judging *you*.

1. **Title + one-line claim with the real numbers**
   > Fine-tuned Qwen2.5-Coder-1.5B (QLoRA, free T4) from **X% → Y%** execution accuracy on unseen domains and **59% → Z%** on a real 11-table database. Runs on CPU. [Live demo] · [Dataset] · [Model] · [W&B run]
2. **Try it in 30 seconds:** the Space link + `docker compose up` (3 lines) + a GIF/screenshot of the side-by-side.
3. **Results:** the headline table (from `reports/eval_results.md`), the per-difficulty chart, and one sentence on quantization.
4. **The data story (ETL):**
   - "23.7% of a popular public dataset doesn't run in SQLite": the funnel table plus the ambiguous-`GROUP BY` example.
   - The pipeline diagram and the engineering properties (idempotent, incremental, validated, leakage-safe), each with *how to see it*: `make pipeline` twice → `new=0`.
5. **Training:** QLoRA config table, trainable parameters (about 18M, 1.2%), loss-curve image, time and cost ("1 epoch, N min, free T4").
6. **Evaluation method:** execution accuracy and why exact match is bad, the normalization rules, the domain-held-out split, CIs/McNemar, the error-class shift, and the manual audit of 20 failures (gold-noise rate).
7. **Design decisions & trade-offs:** condensed from `plan/00-context/decisions.md`. Must include: model choice (stability over recency), canonical schema + prefix caching, repair vs drop, domain split, GGUF + llama.cpp for $0 serving, and RAG vs prompting vs fine-tuning *for this task*.
8. **What I'd do next:** DPO with execution feedback (`plan/03-training/next-steps-dpo.md`), larger/real schemas (BIRD/Spider), MinHash dedup at scale, orchestration with Dagster/Airflow when there are scheduled sources, a GPU serving path (vLLM) if traffic needed it.
9. **Repo map + how to reproduce everything:** `make setup` / `pipeline` / `eval-all` / `up`, plus the notebook.
10. **Limitations** (honest), **licenses** and **credits** (Gretel, b-mc2, Chinook, Qwen, Unsloth, llama.cpp).
