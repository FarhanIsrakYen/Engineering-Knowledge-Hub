# Engineering Knowledge Hub

## Local setup

Requires Python 3.12 or newer.

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

Activate the virtual environment, copy `.env.example` to `.env`, then run:

```bash
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`; interactive documentation is at
`http://localhost:8000/docs`.

## Tests

```bash
pytest
```

To run the PostgreSQL integration test, set `EKH_TEST_DATABASE_URL` to a test
database and run:

```bash
pytest -m integration
```

## Docker

```bash
docker compose up --build
```
