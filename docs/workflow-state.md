# Workflow and state

`RECEIVED → RETRIEVING → INSPECTING → DRAFTED → AWAITING_APPROVAL → APPROVED → DISPATCHING → COMPLETED`

Terminal alternatives: `REJECTED`, `FAILED`, `CANCELLED`. A failed dispatch can be `RETRY_PENDING` before returning to `DISPATCHING`; exhausted attempts become `FAILED` with an explicit failure code and operator recovery path.

Graph state holds request context, retrieved citations, read-only tool results, structured recommendation, action draft, and checkpoint metadata. The structured recommendation schema should include summary, evidence, uncertainty, proposed action, and risk level. Validation failures return to a bounded repair step or fail explicitly.

The graph interrupts after draft creation. The API persists the immutable draft version, records the interrupt, and waits. Approval records reviewer, decision, timestamp, draft hash, and reason. Resume requires the matching operation and draft hash; stale approvals fail closed. A rejection completes without dispatch. Approved actions are queued through the business outbox. The graph checkpoint remains the source of agent execution state; operation status is a business projection.

Retries use bounded exponential backoff with jitter. Only transient adapter failures retry. Dispatch attempts reuse the same idempotency key, derived from operation ID, action ID, and approved draft version. Ambiguous provider outcomes must be reconciled before another send.
