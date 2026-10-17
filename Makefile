.PHONY: install run worker lint typecheck test migrate docker-up docker-down

install:
	python -m pip install -e ".[dev]"

run:
	uvicorn app.main:app --reload

worker:
	celery -A app.worker.celery_app:celery_app worker --pool=solo --loglevel=INFO

lint:
	ruff check .

typecheck:
	mypy

test:
	pytest

migrate:
	alembic upgrade head

docker-up:
	docker compose up --build

docker-down:
	docker compose down
