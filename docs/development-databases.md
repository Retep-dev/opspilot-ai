# Hosted development databases

Two separate Neon Free PostgreSQL projects support local development and integration testing:

| Environment variable | Neon project | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `opspilot-dev` | Synthetic development operations and knowledge |
| `TEST_DATABASE_URL` | `opspilot-integration-test` | Disposable integration-test data |

Both use direct TLS connections stored only in the ignored root `.env`. No connection string or password belongs in Git, logs, screenshots, or documentation. Both databases run PostgreSQL 18 with pgvector 0.8.6; the OpsPilot schema uses `halfvec(2048)` and a cosine HNSW index. LangGraph checkpoint tables have been initialized in each database.

To initialize a new database, set `DATABASE_URL` in the process environment and run `python -m app.init_db` from `backend/`. On Windows, the initializer selects the event loop required by Psycopg's async connection. Run integration tests only with `TEST_DATABASE_URL` pointing at a separate disposable database. The test suite creates synthetic records and can change their state.

The development and test projects were verified with a connection check, pgvector distance query, business/checkpoint table check, and the full backend test suite against the test project. Do not point `TEST_DATABASE_URL` at the development database.
