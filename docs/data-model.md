# Data model plan

`backend/app/schema.sql` creates and upgrades the current business schema. `python -m app.init_db` applies it and initializes LangGraph's PostgreSQL checkpoint tables. The SQL is idempotent for the current schema; future changes need versioned migrations.

| Entity | Core fields and constraints |
| --- | --- |
| `users` | ID, tenant ID, identity subject, role (`requester`, `reviewer`, `admin`) |
| `operations` | ID, tenant ID, requester ID, status, graph thread ID, trace ID, timestamps, version |
| `knowledge_documents` | ID, tenant ID, source, access scope, checksum, ingestion version |
| `knowledge_chunks` | Document ID, chunk index, text, embedding vector, unique document/chunk index |
| `action_drafts` | Operation ID, version, payload, payload hash, immutable after approval |
| `approvals` | Operation ID, draft version/hash, reviewer ID, decision, reason, timestamp; one final decision per version |
| `outbox_actions` | Operation ID, approved draft hash, provider, payload, idempotency key unique, status |
| `dispatch_attempts` | Outbox ID, attempt number, provider request ID, result, next retry time |
| `audit_events` | Operation ID, actor ID, event type, timestamp, redacted metadata, trace ID; append only |
| LangGraph checkpoint tables | Managed by the PostgreSQL checkpointer, keyed by graph thread ID |

All tenant-scoped queries must include tenant ID. Store only necessary customer references in operations; redact content from logs and provider error records. Use a database transaction when recording approval and queuing the associated outbox action.
