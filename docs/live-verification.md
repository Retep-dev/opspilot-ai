# Live integration verification

Use only a sandbox tenant, test customer, approved Slack channel, verified sender, and test recipient. Store credentials in the ignored root `.env` or a managed secret store. Never paste keys or bearer tokens into issues, docs, screenshots, or test output.

## Preparation

1. Copy `.env.example` to the project root as `.env`, then fill the NIM, OIDC, Slack, Resend, PostgreSQL, and test-destination variables locally. The provided chat model is `z-ai/glm-5.3`; the embedding model is `nvidia/nemotron-3-embed-1b` (2048 dimensions). Confirm your NVIDIA account grants access to both models. An older `vector(1024)` knowledge table requires a deliberate re-embedding migration before this schema can be applied to an existing database.
2. Run PostgreSQL with pgvector and initialize the schema. Provision separate requester, reviewer, and admin identities in `users` for the sandbox tenant. The reviewer must differ from the requester.
3. Configure Slack `chat:write` access to the test channel and a verified Resend sender, or use Resend's sandbox sender `onboarding@resend.dev` for an account-authorized test recipient. Set `OPSPILOT_LIVE_TEST_MODE=true` to constrain the worker to the configured test channel and recipient and require `[OpsPilot TEST]` at the start of Slack/email bodies and email subjects. Keep the outbox worker stopped until an approved test action exists.

## Verification sequence

1. With the worker stopped, run `cd backend && python -m app.verify_nim`. It loads the ignored root `.env`, makes one synthetic chat completion and query/passage embedding call, and prints only model IDs, status, and embedding lengths. It does not print the key, prompt, or response content.
2. As admin, ingest a synthetic runbook through `POST /knowledge/documents` and add a synthetic account through `PUT /customer-accounts/{customer_id}`. Use a tenant-scoped retrieval query and verify the runbook source is cited.
3. As requester, create an operation with clearly labeled test text. Check that it is `AWAITING_APPROVAL` and that no outbox action can dispatch yet. Inspect the exact draft destination and body.
4. As a different reviewer, approve only a draft addressed to the designated test channel or email recipient. The draft hash in the approval request must match the displayed draft. Verify a pending outbox row appears only after LangGraph resumes.
5. Start the worker for one action at a time. Verify one external Slack message and one email. Compare provider message/email IDs with `outbox_actions.provider_receipt_id` and `dispatch_attempts.provider_request_id`; record IDs in a private verification note without including content or tokens.
6. Simulate a definite transient failure with a fake provider and confirm `RETRY_PENDING`, bounded backoff, the same idempotency key, and eventual receipt persistence. Simulate an ambiguous outcome and verify `DELIVERY_UNKNOWN` blocks automatic retry. Reconcile only after checking provider evidence.

Do not mark a row “Verified live” in the README until the corresponding real provider call and receipt check succeed. Provider mock tests and CI do not count as live verification.
