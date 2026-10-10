# Verification evidence

Recorded on 2026-10-09 and 2026-10-10 with synthetic inputs. Credentials, bearer tokens, private keys, connection strings, and message bodies are excluded from this record.

| Capability | Classification | Evidence |
| --- | --- | --- |
| NIM chat generation | Live verified | `z-ai/glm-5.3` returned a schema-valid recommendation and draft in the hosted RAG flow. |
| NIM embeddings | Live verified | `nvidia/nemotron-3-embed-1b` returned 2048-dimensional query and passage vectors. |
| Knowledge ingestion and RAG | Live verified | A synthetic runbook was embedded and stored in Neon pgvector, retrieved by tenant, and cited in a recommendation that stopped at `AWAITING_APPROVAL`. |
| OIDC-authenticated API approval | Live verified with local issuer | A locally generated RS256 token and JWKS reached the real FastAPI routes with no dependency override. Missing token returned 401; a requester decision returned 403 with zero outbox actions. After human approval of the exact draft hash, a distinct reviewer token returned 200 from `POST /operations/{id}/decision`, persisted the approval, and released exactly one pending email action. A hosted identity provider was not used. |
| Slack dispatch | Live verified | The approved test message reached channel `C0C824TT134`; receipt `C0C824TT134:1791601274.938129` matches `outbox_actions.provider_receipt_id` and `dispatch_attempts.provider_request_id`. The action is `sent` with one attempt and no duplicate dispatch. |
| Resend email dispatch | Live verified | After the exact draft received human approval through the OIDC API, one `[OpsPilot TEST]` message was sent from `onboarding@resend.dev` only to the configured test recipient. Receipt `01a123cf-0c64-76f6-83d4-a1abdb3f6766` matches both PostgreSQL receipt fields. The action is `sent`, the operation is `COMPLETED`, and the attempt count is one. |
| Approval boundary, retries, ambiguous outcomes, reconciliation, idempotency | Integration-tested | The backend suite exercises PostgreSQL business state and outbox transitions against a separate Neon integration-test database, with fake providers for controlled errors and receipts. |
| Persisted customer account adapter | Integration-tested and used live | Tenant-scoped PostgreSQL account data supplied the synthetic account status during the hosted RAG flow. |
| Production identity provider | Mocked / unverified | The OIDC API route used a local cryptographic test issuer; provider login, key rotation, and hosted issuer configuration remain unverified. |
| Production deployment and web UI | Mocked / unverified | Railway configuration is present, but no deployment has been performed. The frontend remains a scaffold with no UI. |
| Live retry and unknown-outcome recovery | Mocked / unverified | Deterministic PostgreSQL integration tests cover these paths; no real provider failure or ambiguous delivery was induced. |

Both approved live sends used exact test destinations. Resend API acceptance and receipt persistence were verified; mailbox delivery was not independently confirmed. PostgreSQL integration tests use a separate disposable pgvector database. Provider receipt IDs are retained here as nonsecret evidence; detailed request and response logs stay local.
