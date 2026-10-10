# Railway deployment configuration

This repository contains configuration for two Railway services using the same `backend/` root. Deployment is not automatic and has not been performed by this milestone.

1. Provision a PostgreSQL service **with pgvector**. Railway's standard PostgreSQL image does not include pgvector. Use a pgvector-capable template and a private `DATABASE_URL`.
2. Create an API service from this repository. Set Root Directory to `/backend` and Config File to `/backend/railway.api.json`. Give the API a public domain. `/ready` checks required authentication/model configuration and a database connection.
3. Create a worker service from the same repository. Set Root Directory to `/backend` and Config File to `/backend/railway.worker.json`. Do not assign it a public domain. Start it only after the API has applied the schema and checkpoint setup.
4. Set service variables in Railway, never in Git: `DATABASE_URL`, `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`, `NVIDIA_NIM_API_KEY`, `NVIDIA_CHAT_MODEL`, `NVIDIA_EMBEDDING_MODEL`, `SLACK_BOT_TOKEN`, `RESEND_API_KEY`, and `EMAIL_FROM`. The API needs OIDC and NIM variables; the worker needs database and provider variables. Set `NVIDIA_NIM_BASE_URL` and `NVIDIA_EMBEDDING_URL` only when using non-default endpoints. For sandbox dispatch set `OPSPILOT_LIVE_TEST_MODE=true`, `SLACK_TEST_CHANNEL_ID`, and `TEST_RECIPIENT_EMAIL` on the worker.
5. Provision requester, reviewer, and admin user rows through a trusted administrative database path. Do not expose a public self-provisioning endpoint. Configure a sandbox Slack channel and a verified Resend sender before enabling the worker.
6. Enable database backups, restrict database networking, and review tenant access and logs. Keep API and worker at one replica until migration locking and worker scaling have been tested. The worker's `SKIP LOCKED` claim prevents concurrent claims, but database migration ownership still needs a dedicated deployment step before multi-replica rollout.

The application does not deploy the frontend. The customer account table is local persisted sample data, written only by an admin API endpoint.
