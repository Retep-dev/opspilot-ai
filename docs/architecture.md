# Architecture

## Ownership

LangGraph owns the agent graph, durable checkpoints, interrupts, and resume semantics. A request uses a stable graph thread ID tied to an operation ID. PostgreSQL-backed checkpoints must be configured before the graph runs in production.

FastAPI and PostgreSQL own operation records, approval decisions, audit events, dispatch attempts, retry policy, idempotency, and authorization. Resume is initiated by an API command after checking reviewer role and draft version. The graph cannot directly send Slack messages or email.

RAG ingestion writes tenant-scoped document chunks and embeddings to pgvector. Retrieval filters by tenant and document access. A read-only PostgreSQL customer-data adapter supplies tool results from an admin-managed local account table. Model and embedding adapters target NVIDIA NIM; credentials remain server-side.

Slack and email adapters receive an approved immutable action payload. A transactional outbox and unique idempotency key prevent duplicate sends across retries. Provider request IDs and responses are audited with sensitive fields redacted. n8n is optional for inbound triggers and edge delivery, never for checkpoints or approvals.

The current implementation uses Slack and Resend adapters. The outbox action begins `held`, becomes `pending` only after graph resume, and is claimed with PostgreSQL `SKIP LOCKED`. A worker crash or ambiguous provider response moves it to `unknown`; an administrator must reconcile it using provider evidence. Resend idempotency keys have a provider retention window, so an unknown action is never automatically retried after an ambiguous response. The worker runs separately from FastAPI and LangGraph.

## Trust boundaries

The requester creates and views their own operations. A reviewer decides on a pending draft. An admin manages access and recovery. Every endpoint enforces identity and tenant scope server-side. Retrieved text and tool output are untrusted input, never authority to bypass approval. External actions need an exact approved payload hash.

## Observability

Every API request, graph run, tool call, retrieval, approval, and dispatch attempt carries an operation ID and trace ID. Structured logs redact secrets and customer content. Metrics include graph failure rate, approval wait time, retrieval latency, dispatch attempts, and dead-letter count.
