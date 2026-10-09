# OpsPilot AI

An approval-gated AI operations agent. The backend now includes a PostgreSQL schema, a checkpointed LangGraph draft and review flow, and a business-state coordinator. External delivery and HTTP operation endpoints are future work.

## Intended flow

1. A requester submits an operations request.
2. LangGraph retrieves internal knowledge from PostgreSQL/pgvector and calls read-only customer-data tools.
3. The agent produces a validated recommendation and a draft action.
4. A reviewer approves or rejects the exact draft. LangGraph resumes from its interrupt only after FastAPI verifies the approval.
5. FastAPI dispatches approved actions through Slack or email adapters with idempotency keys, retries, and an audit trail.

See [architecture](docs/architecture.md), [workflow](docs/workflow-state.md), and [data model](docs/data-model.md).

## Stack and boundaries

- `frontend/`: Next.js and TypeScript application scaffold. UI design is intentionally deferred.
- `backend/`: FastAPI health endpoint, LangGraph flow, business service, PostgreSQL schema, and provider interfaces.
- PostgreSQL with pgvector stores business records, knowledge embeddings, and durable graph checkpoints.
- NVIDIA NIM can serve chat and embeddings behind model interfaces. Local tests use fakes.
- n8n may connect edge systems later; it never owns workflow state.

## Local development

Copy `.env.example` to `.env` and fill local-only values. Never commit `.env`. Run `docker compose up --build` for PostgreSQL, API, and frontend scaffold. The backend container initializes the business schema and LangGraph checkpoint tables before serving. The API health endpoint is `http://localhost:8000/health`; the frontend scaffold is at `http://localhost:3000`. Docker Compose needs a local Docker daemon.

For backend work: `cd backend`, create a Python 3.12 virtual environment, install `pip install -e '.[dev]'`, then run `ruff check .`, `ruff format --check .`, and `pytest`. For frontend work: `cd frontend`, run `npm install`, `npm run lint`, and `npm run typecheck`.

The graph can be constructed with `build_graph(retriever, customer_data, checkpointer)`; `OperationService` records drafts and decisions against PostgreSQL. The current draft is deterministic and must be reviewed. A pgvector retriever is available when a 1024-dimension embedding adapter is configured. There is no production identity provider or external dispatch worker yet, so operation endpoints are not exposed.

The next milestone is authenticated operation and review endpoints, an NVIDIA NIM model and embedding adapter, a real ingestion path, and an outbox dispatcher with provider fakes in tests.
