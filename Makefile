.PHONY: ui-smoke eval eval-all report setup test lint pipeline pipeline-demo-incremental push-dataset eval app run up down

setup:
	uv sync --all-groups

lint:
	uv run ruff check .

test: lint
	uv run pytest

pipeline:
	uv run python -m text2sql.etl.pipeline run

# --limit then full: the second run should only touch the remaining rows
pipeline-demo-incremental:
	rm -rf data/interim data/state
	uv run python -m text2sql.etl.pipeline run --limit 50000
	uv run python -m text2sql.etl.pipeline run

push-dataset:
	uv run python -m text2sql.etl.pipeline run --push

# make eval MODEL=base-q4 SET=chinook  (a llama-server must already be running)
eval:
	uv run python -m text2sql.eval.run --model $(MODEL) --set $(SET)

eval-all:
	./scripts/eval_all.sh

report:
	uv run python -m text2sql.eval.compare

app:
	uv run python -m text2sql.app.main

run:
	./run.sh

up:
	docker compose up -d

down:
	docker compose down

ui-smoke:
	uv run --with playwright python scripts/ui_smoke.py
