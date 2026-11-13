FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# which dependency groups to install: the app needs "app"; the etl/eval services add theirs
ARG UV_GROUPS="--group app"

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-cache --no-dev --no-install-project $UV_GROUPS

COPY src ./src
COPY configs ./configs
COPY data/demo ./data/demo
COPY data/eval ./data/eval
COPY reports ./reports
RUN uv sync --frozen --no-cache --no-dev $UV_GROUPS

# no recursive chown here: it would copy the whole venv into another layer
RUN useradd -m -u 1000 user
USER user
ENV PATH="/app/.venv/bin:$PATH" APP_HOST=0.0.0.0
EXPOSE 7860
CMD ["python", "-m", "text2sql.app.main"]
