# Next step (designed, not built today): DPO with execution feedback

Goes into the README as "What I'd do next". It shows you understand DPO beyond the definition.

## Why DPO fits this task unusually well
DPO needs (prompt, chosen, rejected) pairs. Usually that means human preference labels. Here **the database is the labeler**: run the SQL and compare it with the reference result.

## Recipe
1. From the SFT model, sample **k=8** completions per training question (temperature 0.8).
2. Execute each one. A completion that matches the reference result is a **chosen** candidate. A wrong result, an error or an empty result is a **rejected** candidate.
3. Keep only questions with at least 1 chosen **and** at least 1 rejected. These are the "hard but learnable" ones; questions where all 8 pass or all 8 fail teach nothing.
4. Pair them: (shortest correct, a typical failure). Prefer a rejected candidate with a *schema-linking* error (`no such column`), since that's the dominant failure mode we measured.
5. `trl.DPOTrainer` on the SFT adapter: β=0.1, LR 5e-6, 1 epoch, a reference model = the frozen SFT model (implicit with PEFT).
6. Evaluate exactly as before. Expect gains on hard/join items, and watch for verbosity or reward hacking (e.g. adding `DISTINCT` everywhere).

## Related concepts to be ready to discuss
- **RLHF (PPO)** trains a reward model and then runs online RL. **DPO** turns preference learning into a classification-like loss on log-prob ratios, with no reward model.
- **GRPO** / RL with verifiable rewards: execution accuracy *is* a verifiable reward, so this task is also a natural fit for online RL. That's the 2025–26 trend (reasoning models trained with verifiable rewards).
- **Distillation:** an alternative data source is to generate SQL with a frontier model, keep only what executes correctly, and then train on it. That's the same execution filter as our ETL validation.
