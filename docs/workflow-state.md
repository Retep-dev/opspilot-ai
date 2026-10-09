# Workflow and state

`RECEIVED → RETRIEVING → INSPECTING → DRAFTED → AWAITING_APPROVAL → APPROVED → DISPATCHING → COMPLETED`

The implemented business projection uses `RECEIVED → AWAITING_APPROVAL → APPROVED → DISPATCHING → COMPLETED`, with `RETRY_PENDING`, `DELIVERY_UNKNOWN`, `FAILED`, and `REJECTED` alternatives. Retrieval and inspection are graph nodes; external dispatch runs only in the separate worker.

Terminal alternatives: `REJECTED`, `FAILED`, `CANCELLED`. A failed dispatch can be `RETRY_PENDING` before returning to `DISPATCHING`; exhausted attempts become `FAILED` with an explicit failure code and operator recovery path.

Graph state holds request context, retrieved citations, read-only tool results, structured recommendation, action draft, and checkpoint metadata. The structured recommendation schema should include summary, evidence, uncertainty, proposed action, and risk level. Validation failures return to a bounded repair step or fail explicitly.

The graph interrupts after draft creation. The API persists the immutable draft version, records the interrupt, and waits. Approval records reviewer, decision, timestamp, draft hash, and reason. Resume requires the matching operation and draft hash; stale approvals fail closed. A rejection completes without dispatch. Approved actions are queued through the business outbox. The graph checkpoint remains the source of agent execution state; operation status is a business projection.

Retries use bounded exponential backoff with jitter. Only transient adapter failures retry. Dispatch attempts reuse the same idempotency key, derived from operation ID, action ID, and approved draft version. Ambiguous provider outcomes must be reconciled before another send.

`OperationService.decide` locks the operation row, verifies tenant, reviewer role, separation of requester and reviewer, and the exact draft hash. It commits the approval and held outbox action together, then resumes the graph. `recover_resume` can complete the graph resume after a crash in that gap and releases the held action. The worker uses the same idempotency key across definite retries. Unknown outcomes wait for admin reconciliation and do not retry automatically.
