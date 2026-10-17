# Engineering Knowledge Hub

Engineering Knowledge Hub is a multi-tenant retrieval-augmented generation (RAG)
service for storing engineering documents and answering questions from their
contents. It keeps ingestion, retrieval, answer generation, citations,
conversations, and evaluation behind a versioned FastAPI API.

## Why I built this

Internal technical knowledge tends to fragment across architecture documents,
runbooks, incident reports, and API documentation. Engineers then spend time
finding the right source, reconciling different terminology, and checking whether
an answer is supported by current documentation.

This project explores a practical boundary around that problem: store documents by
organization and workspace, process them outside the upload request, retrieve both
semantic matches and exact technical terms, and require generated answers to cite
the retrieved source chunks.

## Architecture

```mermaid
flowchart LR
    Client[API client] --> API[FastAPI]
    EvalCLI[Evaluation CLI] --> PG
    EvalCLI --> Redis
    EvalCLI --> Qdrant
    EvalCLI --> Models
    EvalCLI --> LLM

    API --> PG[(PostgreSQL)]
    API --> MinIO[(MinIO object storage)]
    API --> Redis[(Redis)]
    API --> Qdrant[(Qdrant)]
    API --> Models[FastEmbed embedding and reranker models]
    API --> LLM[OpenAI-compatible LLM API]

    API -- enqueue ingestion --> Redis
    Redis -- Celery task --> Worker[Celery worker]
    Worker --> MinIO
    Worker --> PG
    Worker --> Qdrant
    Worker --> Models
```

FastAPI handles authentication, tenant-aware API operations, retrieval, generation,
conversations, and evaluations. PostgreSQL stores users, tenant metadata, document
metadata, chunks, conversations, and evaluation results. File bytes live in MinIO,
not PostgreSQL. Redis is the Celery broker, query-embedding cache, and rate-limit
store. Qdrant stores chunk vectors and tenant-filterable payload metadata.

The application exposes liveness at `/health`, dependency readiness at `/ready`,
OpenAPI documentation at `/docs`, and Prometheus-compatible metrics at `/metrics`.
Requests receive an `X-Request-ID`, and request/application logs are emitted as
structured JSON.

## RAG Pipeline

### Ingestion

```text
document upload
  -> object storage
  -> pending database record
  -> Celery task
  -> parsing
  -> recursive chunking
  -> embedding
  -> Qdrant vectors + PostgreSQL chunks
  -> ready or failed status
```

Uploads return `202 Accepted`; ingestion does not run inside the HTTP request. The
worker supports PDF, Markdown, and plain-text files. Chunk records retain document
and chunk identifiers plus page numbers or section titles when the parser can
extract them. Reprocessing replaces a document's vectors and chunks rather than
appending duplicates.

### Query

```text
question
  -> optional query rewriting
  -> hybrid retrieval
       -> Qdrant semantic search
       -> PostgreSQL full-text search
  -> Reciprocal Rank Fusion
  -> optional reranking
  -> top-k context construction
  -> LLM generation
  -> answer with source citations
```

The original question is retained for generation; a rewritten question is used
only for retrieval. Rewriting is disabled by default. Hybrid retrieval is the
default, while `vector` and `lexical` modes remain configurable. Reranking is
enabled by default and selects the final context from a larger candidate set.

The non-streaming query endpoint returns an answer and source records containing
the document, filename, page when available, chunk ID, and retrieval score. If no
context passes the relevance threshold, the service returns an explicit
insufficient-context answer instead of asking the model to improvise.

Conversations use the same retrieval pipeline and stream assistant output through
Server-Sent Events. Only a bounded recent history is supplied to the query
rewriter; the complete conversation is not copied into every generation prompt.
Completed assistant messages and their citations are persisted.

## Technical decisions

### Why FastAPI

The API is asynchronous at database and network boundaries, and FastAPI provides
typed request validation, dependency-based authorization checks, lifespan resource
management, and OpenAPI output without an additional framework layer.

### Why PostgreSQL

Users, memberships, document state, conversations, and evaluation runs are
relational data with useful uniqueness and foreign-key constraints. PostgreSQL also
provides the full-text search used by lexical retrieval, avoiding another search
service.

### Why Qdrant

Qdrant provides vector similarity search and payload filtering. Each indexed chunk
contains organization and workspace identifiers, so semantic retrieval can apply
tenant filters before results are returned.

### Why Redis

Redis backs Celery task delivery, per-user rate limiting for expensive endpoints,
and caching of repeated query embeddings. Cached keys contain a query hash rather
than the question text.

### Why background workers

PDF parsing, chunking, embedding, and vector indexing can outlive a normal HTTP
request. A Celery worker lets uploads return quickly and records explicit
`pending`, `processing`, `ready`, or `failed` states.

### Why hybrid search

Embeddings handle equivalent wording well, while PostgreSQL full-text search can
recover exact identifiers, configuration keys, and error codes. Reciprocal Rank
Fusion combines their rankings without a hand-tuned weighted scoring formula.

### Why reranking

First-stage retrieval favors recall. The reranker scores query/chunk pairs from the
candidate pool before context construction, improving ordering at the cost of an
additional local model inference step.

## Multi-tenancy and security

Users can belong to multiple organizations. Organization membership has one of
three roles: `owner`, `admin`, or `member`. Creating an organization makes the
creator its owner. Owners and admins can add existing users and create workspaces;
all members can access workspaces belonging to their organization. A document can
be deleted by its creator or an organization owner/admin.

Authorization is resolved server-side by joining each organization, workspace,
document, conversation, or evaluation record to the authenticated user's
membership. Resources outside that membership are returned as not found. Qdrant
searches additionally filter by both organization ID and workspace ID. Conversation
records are restricted to the user who created them.

Passwords are hashed with Argon2. Authentication uses configurable JWT access and
refresh tokens, with secrets loaded from environment settings. Invalid login
responses are generic. Production configuration rejects debug mode and the default
MinIO credentials. Query, search, conversation-message, and evaluation endpoints
use a Redis-backed per-user rate limit.

## RAG evaluation

An evaluation dataset contains a question, an expected answer, and one or more
expected document IDs. Runs can be started with the API or the `ekh-evaluate` CLI,
and their per-item results and aggregates are stored in PostgreSQL.

Deterministic retrieval metrics are computed directly from expected and retrieved
document IDs:

- Hit Rate at K
- Recall at K
- Mean Reciprocal Rank
- Retrieval, generation, and total latency

An optional LLM judge produces answer-relevance and groundedness scores plus a
reason. These scores are model judgments, not objective measurements: they depend
on the judge model, prompt, expected answer, and retrieved context. They are stored
separately from deterministic metrics.

The example dataset in `examples/evaluation_dataset.json` uses placeholder document
IDs. Upload the sample documents first, then replace those IDs with the IDs returned
by the API before running it.

## Running locally

Requirements:

- Docker with Docker Compose
- An OpenAI-compatible API key for query generation, rewriting when enabled, and
  optional LLM judging

Create the environment file and replace `EKH_JWT_SECRET` with a random value of at
least 32 characters. Set `EKH_LLM_API_KEY` before using generation endpoints.

```bash
cp .env.example .env
docker compose build
docker compose up -d db minio redis qdrant
docker compose run --rm api alembic upgrade head
docker compose up -d api worker
docker compose ps
```

In PowerShell, use `Copy-Item .env.example .env` instead of `cp`.

The API is available at `http://localhost:8000`, MinIO's console at
`http://localhost:9001`, and Qdrant's dashboard at
`http://localhost:6333/dashboard`. The embedding and reranking models are downloaded
on first use and cached in the `embedding_models` volume.

To run the Python processes on the host while keeping infrastructure in Docker:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
docker compose up -d db minio redis qdrant
alembic upgrade head
uvicorn app.main:app --reload
```

In PowerShell, replace the activation command with
`.\.venv\Scripts\Activate.ps1`. Start the worker in a second activated terminal:

```bash
celery -A app.worker.celery_app:celery_app worker --pool=solo --loglevel=INFO
```

Stop the Docker services with:

```bash
docker compose down
```

## Tests

Install development dependencies, then run the default test suite and quality
checks:

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy
pre-commit run --all-files
```

`pytest` enforces the configured coverage floor and writes `coverage.xml`. Tests
requiring PostgreSQL are skipped unless `EKH_TEST_DATABASE_URL` points to a migrated
test database. The following POSIX-shell commands create that database and run the
opt-in PostgreSQL, MinIO, and Qdrant integration tests:

```bash
docker compose up -d db minio redis qdrant
docker compose exec db createdb -U ekh ekh_test
EKH_DATABASE_URL=postgresql+asyncpg://ekh:ekh@localhost:5432/ekh_test alembic upgrade head
export EKH_TEST_DATABASE_URL=postgresql+asyncpg://ekh:ekh@localhost:5432/ekh_test
export EKH_TEST_OBJECT_STORAGE=true
export EKH_TEST_QDRANT=true
pytest -m integration
```

The `createdb` command is needed only once. Use PowerShell's `$env:NAME="value"`
syntax instead of `export`, and set `$env:EKH_DATABASE_URL` before running Alembic,
on Windows. The CI workflow runs linting, type checking, migrations, and tests with
PostgreSQL and Redis services.

## Example API usage

Register and log in:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"engineer@example.com","password":"correct horse battery staple","display_name":"Example Engineer"}'

curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"engineer@example.com","password":"correct horse battery staple"}'
```

Copy `access_token` from the login response, then create an organization and a
workspace. Copy the returned IDs into the following commands.

```bash
export TOKEN='<access-token>'

curl -X POST http://localhost:8000/api/v1/organizations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Platform Engineering","slug":"platform-engineering"}'

export ORGANIZATION_ID='<organization-id>'

curl -X POST "http://localhost:8000/api/v1/organizations/$ORGANIZATION_ID/workspaces" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Production Operations","description":"Runbooks and incident documentation"}'
```

Upload a document and wait until its status becomes `ready`:

```bash
export WORKSPACE_ID='<workspace-id>'

curl -X POST "http://localhost:8000/api/v1/workspaces/$WORKSPACE_ID/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@examples/documents/postgresql_runbook.md;type=text/markdown"

curl "http://localhost:8000/api/v1/workspaces/$WORKSPACE_ID/documents" \
  -H "Authorization: Bearer $TOKEN"
```

Run a grounded query:

```bash
curl -X POST "http://localhost:8000/api/v1/workspaces/$WORKSPACE_ID/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"How should a PostgreSQL readiness failure be investigated?","top_k":5}'
```

Create a conversation and stream a follow-up response:

```bash
curl -X POST "http://localhost:8000/api/v1/workspaces/$WORKSPACE_ID/conversations" \
  -H "Authorization: Bearer $TOKEN"

export CONVERSATION_ID='<conversation-id>'

curl -N -X POST "http://localhost:8000/api/v1/conversations/$CONVERSATION_ID/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"What should I check next?","top_k":5}'
```

Run the example evaluation after replacing its placeholder document IDs:

```bash
ekh-evaluate examples/evaluation_dataset.json --workspace-id "$WORKSPACE_ID"
```

## Project structure

```text
app/
  api/          HTTP routes and request dependencies
  core/         configuration, logging, errors, middleware, and metrics
  db/           async SQLAlchemy engine and session lifecycle
  models/       SQLAlchemy models
  schemas/      Pydantic request and response models
  services/     authentication, tenancy, documents, retrieval, queries, and evaluation
  ingestion/    parsers and recursive chunking
  embeddings/   embedding provider and Redis query cache
  rag/          prompts, query rewriting, and reranking
  llm/          LLM provider boundary and OpenAI-compatible implementation
  storage/      object-storage boundary and S3-compatible implementation
  vector/       vector-store boundary and Qdrant implementation
  worker/       Celery application and ingestion task
  cli/          evaluation command
migrations/     Alembic migrations
tests/          unit, API, and opt-in integration tests
examples/       sample documents and evaluation dataset
```

## Trade-offs / limitations

- Parsing is limited to text-based PDF, Markdown, and plain text. There is no OCR,
  image extraction, table reconstruction, or scanned-PDF support.
- The concrete embedding and reranking implementations use local FastEmbed models;
  first use requires a model download and can be slow.
- The concrete LLM implementation uses an OpenAI-compatible API. The application
  has a provider boundary, but no second LLM implementation is included.
- Refresh tokens are stateless. There is no server-side revocation, reuse detection,
  account verification, or password recovery.
- PostgreSQL, MinIO, and Qdrant writes are not coordinated by a distributed
  transaction or outbox. Retry behavior limits duplicate chunks, but cannot remove
  every partial-failure case.
- Evaluation runs execute synchronously and the included example dataset is small.
  It is a starting point for regression testing, not evidence of general RAG
  quality.
- List endpoints are not paginated.
- Docker Compose uses development credentials, exposes infrastructure ports, and is
  not equivalent to production orchestration, secret management, backups, TLS, or
  network isolation.
- The test suite has opt-in external-service coverage, but MinIO, Qdrant, the worker,
  and streaming disconnect behavior are not exercised by the default CI services.

## Future improvements

- Add OCR and more structure-aware parsing for scanned PDFs and technical tables.
- Add refresh-token rotation, revocation, account verification, and password reset.
- Add pagination to organization, workspace, document, and conversation listings.
- Introduce an outbox or reconciliation process for database, object-storage, and
  vector-index consistency.
- Expand evaluation datasets with reviewed questions from multiple document types
  and track deterministic regressions in CI.
- Add end-to-end worker, MinIO, Qdrant, and SSE disconnect tests.
- Provide deployment manifests with managed secrets, TLS, backups, and private
  infrastructure networking.
