# Submission checklist (run it top to bottom before sending)

## Links work in a private/incognito window
- [ ] GitHub repo is public; the README's first screen shows the results and the demo link
- [ ] HF Space loads; 3 example chips work; base and fine-tuned columns both render
- [ ] HF dataset is public, the card is filled in, `load_dataset(...)` works
- [ ] HF model repos (LoRA + GGUF) are public with cards; `llama-server -hf <repo>:Q4_K_M` works
- [ ] W&B run is public

## Reproducibility, checked on a clean clone
- [ ] `git clone … && docker compose up` → http://localhost:7860 works with **no** `.env`
- [ ] `make setup && make test` is green
- [ ] `make pipeline` reproduces `reports/data_quality.md`; a second run reports `new=0`
- [ ] `make eval-all` reproduces `reports/eval_results.md` (within ±1 pt; llama.cpp greedy decoding can vary slightly across builds and threads)
- [ ] The notebook is committed **with outputs**

## Honesty
- [ ] Every number in the README is copied from a generated report (no hand-typed numbers)
- [ ] Limitations section present; the gold-noise audit is reported
- [ ] Chinook-set provenance stated (LLM-generated, execution-validated, hand-spot-checked)
- [ ] No secrets in git history (`git log -p | grep -iE "hf_|sk-|wandb"` is empty)

## Message to the reviewer (short; draft in `talking-points.md`)
- [ ] 3 links (demo, repo, one-line result) and 2–3 sentences. No wall of text.
