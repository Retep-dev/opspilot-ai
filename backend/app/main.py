"""Authenticated API boundary for operations, review, and knowledge."""

import logging
import os
from contextlib import asynccontextmanager
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, status
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, Field

from app.adapters import PostgresCustomerDataAdapter
from app.auth import OidcSettings, TokenVerifier, require_roles
from app.customer import CustomerAccountInput, CustomerAccountStore
from app.graph import build_graph
from app.knowledge import KnowledgeIngestor, KnowledgeInput
from app.models import ApprovalDecision, OperationRequest
from app.nim import NimClient
from app.observability import current_request_id, end_request, log_event, start_request
from app.outbox import OutboxDispatcher
from app.providers import ResendEmailProvider, SlackProvider
from app.retrieval import PgVectorRetriever
from app.service import Actor, OperationService


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = os.getenv("DATABASE_URL")
    app.state.database_url = database_url
    app.state.token_verifier = None
    app.state.operation_service = None
    app.state.ingestor = None
    app.state.customer_store = (
        CustomerAccountStore(database_url) if database_url else None
    )
    app.state.dispatcher = None
    oidc = [
        os.getenv(name) for name in ("OIDC_ISSUER", "OIDC_AUDIENCE", "OIDC_JWKS_URL")
    ]
    nim = [
        os.getenv(name)
        for name in (
            "NVIDIA_NIM_API_KEY",
            "NVIDIA_CHAT_MODEL",
            "NVIDIA_EMBEDDING_MODEL",
        )
    ]
    if all(oidc):
        app.state.token_verifier = TokenVerifier(OidcSettings(*oidc))
    if database_url and all(nim):
        model = NimClient(
            *nim,
            chat_base_url=os.getenv(
                "NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ),
            embedding_url=os.getenv(
                "NVIDIA_EMBEDDING_URL",
                "https://integrate.api.nvidia.com/v1/embeddings",
            ),
        )
        async with AsyncPostgresSaver.from_conn_string(database_url) as checkpointer:
            graph = build_graph(
                PgVectorRetriever(database_url, model),
                PostgresCustomerDataAdapter(database_url),
                checkpointer,
                model,
            )
            app.state.operation_service = OperationService(database_url, graph)
            app.state.ingestor = KnowledgeIngestor(database_url, model)
            if (
                os.getenv("SLACK_BOT_TOKEN")
                and os.getenv("RESEND_API_KEY")
                and os.getenv("EMAIL_FROM")
            ):
                app.state.dispatcher = OutboxDispatcher(
                    database_url,
                    {
                        "slack": SlackProvider(os.environ["SLACK_BOT_TOKEN"]),
                        "email": ResendEmailProvider(
                            os.environ["RESEND_API_KEY"], os.environ["EMAIL_FROM"]
                        ),
                    },
                )
            try:
                yield
            finally:
                await model.close()
                if app.state.dispatcher:
                    for provider in app.state.dispatcher.providers.values():
                        await provider.close()
    else:
        yield


app = FastAPI(title="OpsPilot AI API", version="0.2.0", lifespan=lifespan)
logger = logging.getLogger(__name__)


@app.middleware("http")
async def request_context(request: Request, call_next):
    token = start_request()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = current_request_id() or ""
        log_event(logger, "http.completed")
        return response
    finally:
        end_request(token)


def get_service(request: Request) -> OperationService:
    service = getattr(request.app.state, "operation_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Operations are not configured")
    return service


def get_ingestor(request: Request) -> KnowledgeIngestor:
    ingestor = getattr(request.app.state, "ingestor", None)
    if ingestor is None:
        raise HTTPException(
            status_code=503, detail="Knowledge ingestion is not configured"
        )
    return ingestor


def get_customer_store(request: Request) -> CustomerAccountStore:
    store = getattr(request.app.state, "customer_store", None)
    if store is None:
        raise HTTPException(
            status_code=503, detail="Customer storage is not configured"
        )
    return store


def get_dispatcher(request: Request) -> OutboxDispatcher:
    dispatcher = getattr(request.app.state, "dispatcher", None)
    if dispatcher is None:
        raise HTTPException(status_code=503, detail="Dispatch is not configured")
    return dispatcher


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready(request: Request) -> dict[str, str]:
    database_url = getattr(request.app.state, "database_url", None)
    if (
        not database_url
        or getattr(request.app.state, "token_verifier", None) is None
        or getattr(request.app.state, "operation_service", None) is None
    ):
        raise HTTPException(
            status_code=503, detail="Required services are not configured"
        )
    try:
        async with await psycopg.AsyncConnection.connect(
            database_url, connect_timeout=3
        ) as conn:
            await conn.execute("SELECT 1")
    except psycopg.Error:
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return {"status": "ready"}


@app.post("/operations", status_code=status.HTTP_201_CREATED)
async def create_operation(
    payload: OperationRequest,
    actor: Actor = Depends(require_roles("requester", "reviewer", "admin")),
    service: OperationService = Depends(get_service),
) -> dict[str, str]:
    operation_id = await service.create(actor, payload)
    return {"id": str(operation_id)}


@app.get("/operations/{operation_id}")
async def get_operation(
    operation_id: UUID,
    actor: Actor = Depends(require_roles("requester", "reviewer", "admin")),
    service: OperationService = Depends(get_service),
) -> dict:
    try:
        return await service.get(actor, operation_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Operation not found") from None


@app.post("/operations/{operation_id}/decision")
async def decide_operation(
    operation_id: UUID,
    payload: ApprovalDecision,
    actor: Actor = Depends(require_roles("reviewer", "admin")),
    service: OperationService = Depends(get_service),
) -> dict[str, str]:
    try:
        await service.decide(actor, operation_id, payload)
    except LookupError:
        raise HTTPException(status_code=404, detail="Operation not found") from None
    except PermissionError:
        raise HTTPException(
            status_code=403, detail="Reviewer cannot approve this operation"
        ) from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    return {"status": payload.decision}


@app.post("/knowledge/documents", status_code=status.HTTP_201_CREATED)
async def ingest_document(
    payload: KnowledgeInput,
    actor: Actor = Depends(require_roles("admin")),
    ingestor: KnowledgeIngestor = Depends(get_ingestor),
) -> dict[str, str]:
    try:
        document_id = await ingestor.ingest(actor.tenant_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    return {"id": str(document_id)}


@app.put("/customer-accounts/{customer_id}")
async def upsert_customer_account(
    customer_id: str,
    payload: CustomerAccountInput,
    actor: Actor = Depends(require_roles("admin")),
    store: CustomerAccountStore = Depends(get_customer_store),
) -> dict[str, str]:
    if payload.customer_id != customer_id:
        raise HTTPException(status_code=422, detail="Customer ID mismatch")
    await store.upsert(actor.tenant_id, payload)
    return {"status": "stored"}


class Reconciliation(BaseModel):
    sent: bool
    evidence: str = Field(min_length=1, max_length=2000)
    receipt_id: str | None = None


@app.post("/outbox/{action_id}/reconcile")
async def reconcile_action(
    action_id: UUID,
    payload: Reconciliation,
    actor: Actor = Depends(require_roles("admin")),
    dispatcher: OutboxDispatcher = Depends(get_dispatcher),
) -> dict[str, str]:
    try:
        await dispatcher.reconcile(
            actor,
            action_id,
            sent=payload.sent,
            evidence=payload.evidence,
            receipt_id=payload.receipt_id,
        )
    except LookupError:
        raise HTTPException(
            status_code=404, detail="Unknown action not found"
        ) from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    return {"status": "reconciled"}
