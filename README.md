# OpsPilot AI

An approval-gated AI operations agent. The backend includes authenticated operations and review endpoints, a checkpointed LangGraph flow, NIM generation and embeddings, tenant-scoped knowledge ingestion, and a separate outbox dispatcher.

## Intended flow

1. A requester submits an operations request.
2. LangGraph retrieves internal knowledge from PostgreSQL/pgvector and calls read-only customer-data tools.
3. The agent produces a validated recommendation and a draft action.
4. A reviewer approves or rejects the exact draft. LangGraph resumes from its interrupt only after FastAPI verifies the approval.
5. A separate outbox worker dispatches approved actions through Slack or email adapters with idempotency keys, retries, and an audit trail.

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

NIM chat and embedding models must be configured before operation endpoints become available. Customer accounts now use a tenant-scoped PostgreSQL table; admins can populate local test accounts through `PUT /customer-accounts/{customer_id}`. Slack uses `chat.postMessage`; email uses Resend's API and idempotency key. The worker sends only actions released after the graph resumes. For sandbox delivery, `OPSPILOT_LIVE_TEST_MODE=true` restricts destinations to the configured test channel and recipient and requires `[OpsPilot TEST]` labels. Definite transient failures use bounded backoff; unknown outcomes are quarantined for admin reconciliation. No live provider request is made by the test suite.

## Verification matrix

| Capability | Live verification | Current evidence |
| --- | --- | --- |
| NIM generation | Verified live | `z-ai/glm-5.3` returned a schema-valid synthetic recommendation and draft |
| NIM embeddings | Verified live | `nvidia/nemotron-3-embed-1b` returned 2048-value query and passage vectors |
| RAG retrieval | Verified live | Synthetic runbook ingested with NIM embeddings and retrieved from Neon pgvector; recommendation cited the runbook and stopped at approval |
| Slack dispatch | Verified live | One human-approved `[OpsPilot TEST]` message reached the approved channel; Slack receipt matched both outbox and dispatch-attempt storage |
| Email dispatch | Verified live | One human-approved `[OpsPilot TEST]` email sent with Resend's sandbox sender to the configured test recipient; receipt matched both PostgreSQL receipt fields |
| OIDC API approval | Verified with local issuer | Signed RS256 tokens reached FastAPI: missing token 401, requester decision 403, reviewer approval 200; a hosted identity provider remains unverified |

The local customer account adapter uses persisted PostgreSQL data in integration tests. The human approval boundary, retries, unknown-outcome quarantine, and receipt persistence are tested against PostgreSQL with fake providers. The development and integration-test databases are separate free Neon projects with pgvector; connection strings are only in the ignored local `.env`. See [database setup](docs/development-databases.md), [live verification](docs/live-verification.md), and [Railway deployment](docs/deployment-railway.md).

The next milestone is deployment validation with a hosted identity provider, production observability, and failure recovery drills. See [verification evidence](docs/verification-evidence.md) for the live, integration-tested, and unverified matrix.
