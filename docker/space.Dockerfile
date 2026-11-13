# One container for a Hugging Face Docker Space: two llama-servers plus the Gradio app.
# The base image is the same pinned llama.cpp build the compose file uses.
FROM ghcr.io/ggml-org/llama.cpp:server@sha256:2103d1f4f2e2e223ad80587dcb39fc15a9f912f29ae1fa9fc1193fe8c1aea82f

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /bin/uv

# Spaces run the container as uid 1000; this image ships an "ubuntu" user on that id
RUN userdel -r ubuntu 2>/dev/null; useradd -m -u 1000 user
USER user
ENV HOME=/home/user UV_PYTHON_INSTALL_DIR=/home/user/.uv-python UV_LINK_MODE=copy \
    PATH=/home/user/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 GRADIO_ANALYTICS_ENABLED=False
WORKDIR /home/user/app

COPY --chown=user pyproject.toml uv.lock ./
RUN uv python install 3.12 && uv sync --frozen --no-cache --no-dev --no-install-project --group app

# Bake both Q4_K_M files into the image so a cold start never waits on the Hub.
# The fine-tuned repo has to be public before the build runs.
ARG HF_USER=parthasaradhi789
RUN mkdir models \
 && curl -fL --http1.1 --retry 5 --retry-all-errors -o models/base.gguf \
      https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf \
 && curl -fL --http1.1 --retry 5 --retry-all-errors -o models/ft.gguf \
      https://huggingface.co/${HF_USER}/text2sql-qwen2.5-coder-1.5b-GGUF/resolve/main/Qwen2.5-Coder-1.5B-Instruct.Q4_K_M.gguf

COPY --chown=user README.md ./
COPY --chown=user src ./src
COPY --chown=user configs ./configs
COPY --chown=user data/demo ./data/demo
COPY --chown=user data/eval ./data/eval
COPY --chown=user reports ./reports
RUN uv sync --frozen --no-cache --no-dev --group app

# llama-server finds its shared libraries next to the binary, not relative to our workdir
ENV LD_LIBRARY_PATH=/app
COPY --chown=user docker/space-entrypoint.sh ./
EXPOSE 7860
ENTRYPOINT ["bash", "space-entrypoint.sh"]
