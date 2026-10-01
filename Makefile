.PHONY: install run test migrate docker-up docker-down

install:
	python -m pip install -e ".[dev]"

run:
	uvicorn app.main:app --reload

test:
	pytest

migrate:
	alembic upgrade head

docker-up:
	docker compose up --build

docker-down:
	docker compose down
