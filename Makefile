.PHONY: setup test lint pipeline push-dataset eval app run up down

setup:
	uv sync --all-groups

lint:
	uv run ruff check .

test: lint
	uv run pytest

pipeline:
	uv run python -m text2sql.etl.pipeline run

push-dataset:
	uv run python -m text2sql.etl.pipeline run --push

app:
	uv run python -m text2sql.app.main

run:
	./run.sh

up:
	docker compose up -d

down:
	docker compose down
