# OpsPilot AI

An approval-gated AI operations agent. This repository begins with an architecture and development scaffold; no agent execution or external action is implemented yet.

## Intended flow

1. A requester submits an operations request.
2. LangGraph retrieves internal knowledge from PostgreSQL/pgvector and calls read-only customer-data tools.
3. The agent produces a validated recommendation and a draft action.
4. A reviewer approves or rejects the exact draft. LangGraph resumes from its interrupt only after FastAPI verifies the approval.
5. FastAPI dispatches approved actions through Slack or email adapters with idempotency keys, retries, and an audit trail.

See [architecture](docs/architecture.md), [workflow](docs/workflow-state.md), and [data model](docs/data-model.md).

## Stack and boundaries

- `frontend/`: Next.js and TypeScript application scaffold. UI design is intentionally deferred.
- `backend/`: FastAPI, LangGraph integration boundary, and provider interfaces.
- PostgreSQL with pgvector stores business records, knowledge embeddings, and durable graph checkpoints.
- NVIDIA NIM can serve chat and embeddings behind model interfaces. Local tests use fakes.
- n8n may connect edge systems later; it never owns workflow state.

## Local development

Copy `.env.example` to `.env` and fill local-only values. Never commit `.env`. Run `docker compose up --build` for PostgreSQL, API, and frontend scaffold. The API health endpoint is `http://localhost:8000/health`; the frontend scaffold is at `http://localhost:3000`. Docker Compose needs a local Docker daemon.

For backend work: `cd backend`, create a Python 3.12 virtual environment, install `pip install -e '.[dev]'`, then run `ruff check .`, `ruff format --check .`, and `pytest`. For frontend work: `cd frontend`, run `npm install`, `npm run lint`, and `npm run typecheck`.

The first implementation milestone is a real database schema and durable approval-gated LangGraph flow, with mock customer data and fake provider adapters in integration tests.
