# HF Space deployment (CPU, Docker SDK)

## ⚠️ Check first (T6.0, 2 minutes): can your account run a free Docker Space?
- The HF docs still list **CPU Basic: 2 vCPU / 16 GB, no hourly cost**.
- But mid-2026 community threads report that **creating a Space that runs on compute (Gradio or Docker) now requires a paid plan**. One reportedly quotes HF staff saying cpu-basic requires PRO, and others report a "cpu-basic quota 0" on new accounts.
- **Test:** go to huggingface.co/new-space → SDK Docker → is "CPU basic · Free" selectable, and does a hello-world build start?

| Outcome | What we do |
|---|---|
| Free Docker Space works | the plan below, as written |
| Needs PRO (about $9/month) | **Recommended if you're OK with it:** it's the cheapest way to get a permanent public URL, and it's still not a GPU bill. Cancel after the review |
| Neither | **Free fallback:** run `docker compose up` on your Mac during the review window and expose it with a **Cloudflare quick tunnel** (`brew install cloudflared && cloudflared tunnel --url http://localhost:7860`). That gives a public `*.trycloudflare.com` URL with no account. Or use Gradio's `share=True` link. Both work only while your Mac is awake, so say so in the message: "live until <date>; or run `docker compose up`" |

Measured local performance applies to the tunnel option. It actually runs **faster** than the Space would, because the Mac's CPUs are faster.

## Space settings
- Owner/name: `HF_USER/text2sql-specialist`. **SDK: Docker**. Hardware: **CPU basic (free): 2 vCPU, 16 GB RAM**. Public.
- The Space repo `README.md` header:
  ```yaml
  ---
  title: Text-to-SQL Specialist
  emoji: 🗄️
  colorFrom: blue
  colorTo: green
  sdk: docker
  app_port: 7860
  pinned: false
  license: apache-2.0
  ---
  ```

## What gets uploaded (`scripts/deploy_space.py`)
The script assembles a temp folder, then calls `HfApi().upload_folder(repo_id=…, repo_type="space", folder_path=tmp)`:
- `Dockerfile` (= `docker/space.Dockerfile`), `space-entrypoint.sh`, `pyproject.toml`, `uv.lock`, `src/`, `configs/`, `data/demo/`, `data/eval/`, `reports/` (for the Results and Pipeline tabs), and the Space `README.md` above.
- **Not uploaded:** `data/raw|interim|processed`, notebooks, tests, runs.
- Add `scripts/deploy_space.py` to the repo tree.

## Build-time model baking
The Dockerfile downloads both Q4_K_M GGUFs at build time (about 2.2 GB) so a cold start doesn't depend on Hub downloads. The fine-tuned GGUF repo must be **public** before the Space builds.

## Verification steps (T6)
1. Locally: `docker build -f docker/space.Dockerfile -t t2s-space .` then `docker run --rm --cpus 2 -p 7860:7860 t2s-space`. The UI works, and the warm Chinook request on both models takes under 3–4 s.
2. Deploy → watch the Space build logs → open the Space → run 3 example chips → **record the real Space latency** for the README.
3. Wait about 5 minutes and reload: still warm. Mention the sleep behavior in the README: "first visit after inactivity: ~1 min".

## If the Space is too slow or fails to build
- Too slow with two models at once: set `APP_SEQUENTIAL=1` as a Space variable (no rebuild).
- Build fails on uv Python: fall back to apt `python3-venv` (see docker.md).
- Last resort: a Gradio-SDK Space that shows only the fine-tuned model via `llama-cpp-python`, with a pinned version **known to install**. Verify the wheel first, because the 0.3.35 Metal wheel was corrupt today. The README then points to `docker compose up` for the side-by-side.
