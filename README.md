# Engineering Knowledge Hub

## Local setup

Requires Python 3.12 or newer.

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

Activate the virtual environment, copy `.env.example` to `.env`, then run:

Replace `EKH_JWT_SECRET` in `.env` with a random secret of at least 32 characters.
Set `EKH_LLM_API_KEY` to enable the RAG query endpoint.

```bash
docker compose up -d db minio redis qdrant
alembic upgrade head
uvicorn app.main:app --reload
```

In another terminal, start the ingestion worker:

```bash
celery -A app.worker.celery_app:celery_app worker --pool=solo --loglevel=INFO
```

The API is available at `http://localhost:8000`; interactive documentation is at
`http://localhost:8000/docs`.

## Retrieval

Retrieval defaults to `hybrid`, combining semantic similarity with PostgreSQL
full-text search through Reciprocal Rank Fusion. Semantic search handles equivalent
wording, while lexical search recovers exact identifiers such as incident codes,
API symbols, and configuration keys that embeddings can rank poorly. Set
`EKH_RETRIEVAL_MODE` to `vector`, `lexical`, or `hybrid`; vector-only remains
available for comparison and troubleshooting.

The RAG query path is intentionally linear:

```text
original question
  -> optional retrieval-query rewrite
  -> hybrid retrieval (candidate pool)
  -> optional cross-encoder reranking
  -> top-k context
  -> grounded generation using the original question
```

Rewriting improves retrieval phrasing without changing the user's question in the
generation prompt. Reranking evaluates query/chunk pairs more precisely than the
first-stage retrievers, but costs additional latency. Configure these stages with
`EKH_QUERY_REWRITING_ENABLED`, `EKH_RERANKING_ENABLED`,
`EKH_RAG_CANDIDATE_COUNT`, and `EKH_RAG_DEFAULT_TOP_K`. Stage latency and context
counts are recorded in structured logs rather than exposed in API responses.

## Tests

```bash
pytest
```

To run the PostgreSQL integration test, set `EKH_TEST_DATABASE_URL` to a test
database. Set `EKH_TEST_OBJECT_STORAGE=true` for MinIO and
`EKH_TEST_QDRANT=true` for Qdrant:

```bash
pytest -m integration
```

## Docker

```bash
docker compose up --build
```

MinIO's local console is available at `http://localhost:9001`; Qdrant's dashboard
is available at `http://localhost:6333/dashboard`. Docker Compose also starts Redis
and a Celery worker for document ingestion. The configured embedding model is
downloaded to the shared model cache on first use.

## Security trade-offs

Passwords are hashed with Argon2 and JWT secrets are loaded from the environment.
This portfolio version uses stateless refresh tokens, so issued tokens cannot be
revoked individually and refresh-token reuse is not detected. A production rollout
should add refresh-token rotation with server-side revocation, rate limiting, account
verification, password recovery, and secret rotation. Bearer tokens are returned in
JSON; clients are responsible for storing them securely. Duplicate registration
returns `409`, which reveals whether an email is registered; login failures remain
generic. HS256 is appropriate for this single service, while deployments that share
verification across services should consider asymmetric signing keys.
