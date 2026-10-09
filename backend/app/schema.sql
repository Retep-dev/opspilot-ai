CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    identity_subject text NOT NULL,
    role text NOT NULL CHECK (role IN ('requester', 'reviewer', 'admin')),
    UNIQUE (tenant_id, identity_subject)
);

CREATE TABLE IF NOT EXISTS operations (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    requester_id uuid NOT NULL REFERENCES users(id),
    request_text text NOT NULL,
    customer_id text,
    status text NOT NULL CHECK (status IN (
        'RECEIVED', 'DRAFTING', 'AWAITING_APPROVAL', 'APPROVED',
        'REJECTED', 'DISPATCHING', 'RETRY_PENDING', 'COMPLETED', 'FAILED', 'CANCELLED'
    )),
    graph_thread_id text NOT NULL UNIQUE,
    trace_id uuid NOT NULL,
    failure_code text,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    source text NOT NULL,
    access_scope text NOT NULL,
    checksum text NOT NULL,
    ingestion_version integer NOT NULL,
    UNIQUE (tenant_id, source, ingestion_version)
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    document_id uuid NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    embedding vector(1024),
    PRIMARY KEY (document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS action_drafts (
    operation_id uuid NOT NULL REFERENCES operations(id),
    version integer NOT NULL,
    payload jsonb NOT NULL,
    payload_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (operation_id, version)
);

CREATE TABLE IF NOT EXISTS approvals (
    operation_id uuid NOT NULL,
    draft_version integer NOT NULL,
    draft_hash text NOT NULL,
    reviewer_id uuid NOT NULL REFERENCES users(id),
    decision text NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reason text,
    decided_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (operation_id, draft_version),
    FOREIGN KEY (operation_id, draft_version)
        REFERENCES action_drafts(operation_id, version)
);

CREATE TABLE IF NOT EXISTS outbox_actions (
    id uuid PRIMARY KEY,
    operation_id uuid NOT NULL REFERENCES operations(id),
    draft_version integer NOT NULL,
    draft_hash text NOT NULL,
    provider text NOT NULL CHECK (provider IN ('slack', 'email')),
    payload jsonb NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('pending', 'sending', 'retry_pending', 'sent', 'failed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (operation_id, draft_version)
        REFERENCES action_drafts(operation_id, version)
);

CREATE TABLE IF NOT EXISTS dispatch_attempts (
    outbox_id uuid NOT NULL REFERENCES outbox_actions(id),
    attempt_number integer NOT NULL,
    provider_request_id text,
    result text NOT NULL,
    next_retry_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (outbox_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    operation_id uuid NOT NULL REFERENCES operations(id),
    actor_id uuid REFERENCES users(id),
    event_type text NOT NULL,
    trace_id uuid NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS operations_tenant_requester_idx
    ON operations (tenant_id, requester_id, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_events_operation_idx
    ON audit_events (operation_id, created_at);
CREATE INDEX IF NOT EXISTS outbox_pending_idx
    ON outbox_actions (status, created_at);
CREATE INDEX IF NOT EXISTS knowledge_documents_tenant_scope_idx
    ON knowledge_documents (tenant_id, access_scope);
