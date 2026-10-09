# OpsPilot AI

An approval-gated AI operations agent. The backend includes authenticated operations and review endpoints, a checkpointed LangGraph flow, NIM generation and embeddings, tenant-scoped knowledge ingestion, and a separate outbox dispatcher.

## Intended flow

1. A requester submits an operations request.
2. LangGraph retrieves internal knowledge from PostgreSQL/pgvector and calls read-only customer-data tools.
3. The agent produces a validated recommendation and a draft action.
4. A reviewer approves or rejects the exact draft. LangGraph resumes from its interrupt only after FastAPI verifies the approval.
5. FastAPI dispatches approved actions through Slack or email adapters with idempotency keys, retries, and an audit trail.

See [architecture](docs/architecture.md), [workflow](docs/workflow-state.md), and [data model](docs/data-model.md).

## Stack and boundaries

- `frontend/`: Next.js and TypeScript application scaffold. UI design is intentionally deferred.
- `backend/`: FastAPI endpoints, LangGraph flow, business service, PostgreSQL schema, and provider adapters.
- PostgreSQL with pgvector stores business records, knowledge embeddings, and durable graph checkpoints.
- NVIDIA NIM can serve chat and embeddings behind model interfaces. Local tests use fakes.
- n8n may connect edge systems later; it never owns workflow state.

## Local development

Copy `.env.example` to `.env` and fill local-only values. Never commit `.env`. Run `docker compose up --build` for PostgreSQL, API, and frontend scaffold. The backend container initializes the business schema and LangGraph checkpoint tables before serving. The API health endpoint is `http://localhost:8000/health`. To enable external dispatch after configuring Slack and Resend credentials, run `docker compose --profile dispatch up --build`. Docker Compose needs a local Docker daemon.

For backend work: `cd backend`, create a Python 3.12 virtual environment, install `pip install -e '.[dev]'`, then run `ruff check .`, `ruff format --check .`, and `pytest`. For frontend work: `cd frontend`, run `npm install`, `npm run lint`, and `npm run typecheck`.

Operation endpoints require a configured OIDC issuer, audience, and JWKS URL plus a provisioned user row. Only RS256 bearer tokens with a signed tenant ID are accepted. An administrator must provision `users` rows through a trusted database administration path before login. Requesters can create and view their own operations; reviewers can decide other users' operations; admins can ingest knowledge and reconcile ambiguous deliveries. All access is tenant-scoped.

NIM chat and embedding models must be configured before operation endpoints become available. The customer-data tool remains mock/read-only. Slack uses `chat.postMessage`; email uses Resend's API and idempotency key. The worker sends only actions released after the graph resumes. Definite transient failures use bounded backoff; unknown outcomes are quarantined for admin reconciliation. No live provider request is made by the test suite.

The next milestone is a real customer-data connector, deployment configuration, stronger observability, and live provider sandbox verification.
