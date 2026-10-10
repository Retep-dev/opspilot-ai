"""Runs against a disposable pgvector database in CI."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.adapters import (
    CustomerRecord,
    MockCustomerDataAdapter,
    PostgresCustomerDataAdapter,
)
from app.customer import CustomerAccountInput, CustomerAccountStore
from app.graph import build_graph
from app.knowledge import KnowledgeIngestor, KnowledgeInput
from app.models import ApprovalDecision, Evidence, OperationRequest
from app.outbox import OutboxDispatcher
from app.providers import Receipt, RetryableDeliveryError, UnknownDeliveryOutcome
from app.retrieval import PgVectorRetriever
from app.service import Actor, OperationService


class FakeRetriever:
    async def search(self, tenant_id: str, query: str) -> list[Evidence]:
        return [Evidence(source="runbook", excerpt="Escalate to operations")]


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs PostgreSQL")
def test_approval_persists_outbox_and_resumes_graph() -> None:
    async def scenario() -> None:
        url = os.environ["TEST_DATABASE_URL"]
        schema = Path(__file__).parents[1] / "app" / "schema.sql"
        async with await psycopg.AsyncConnection.connect(url) as conn:
            await conn.execute(schema.read_text(encoding="utf-8"))
        tenant_id, requester_id, reviewer_id = uuid4(), uuid4(), uuid4()
        async with await psycopg.AsyncConnection.connect(url) as conn:
            await conn.execute(
                """INSERT INTO users (id, tenant_id, identity_subject, role)
                   VALUES (%s, %s, 'requester-test', 'requester'),
                          (%s, %s, 'reviewer-test', 'reviewer')""",
                (requester_id, tenant_id, reviewer_id, tenant_id),
            )
        async with AsyncPostgresSaver.from_conn_string(url) as checkpointer:
            await checkpointer.setup()
            graph = build_graph(
                FakeRetriever(),
                MockCustomerDataAdapter({"c-1": CustomerRecord("c-1", "active")}),
                checkpointer,
            )
            service = OperationService(url, graph)
            operation_id = await service.create(
                Actor(requester_id, tenant_id, "requester"),
                OperationRequest(request_text="Investigate billing", customer_id="c-1"),
            )
            async with await psycopg.AsyncConnection.connect(url) as conn:
                cursor = await conn.execute(
                    "SELECT payload_hash FROM action_drafts WHERE operation_id = %s",
                    (operation_id,),
                )
                draft_hash = (await cursor.fetchone())[0]
            decision = ApprovalDecision(decision="approved", draft_hash=draft_hash)
            await service.decide(
                Actor(reviewer_id, tenant_id, "reviewer"), operation_id, decision
            )
            await service.decide(
                Actor(reviewer_id, tenant_id, "reviewer"), operation_id, decision
            )
            async with await psycopg.AsyncConnection.connect(url) as conn:
                cursor = await conn.execute(
                    """SELECT o.status, a.status, a.idempotency_key
                       FROM operations o JOIN outbox_actions a ON a.operation_id = o.id
                       WHERE o.id = %s""",
                    (operation_id,),
                )
                assert await cursor.fetchone() == (
                    "APPROVED",
                    "pending",
                    f"{operation_id}:1:{draft_hash}",
                )
                cursor = await conn.execute(
                    "SELECT count(*) FROM outbox_actions WHERE operation_id = %s",
                    (operation_id,),
                )
                assert (await cursor.fetchone())[0] == 1
            snapshot = await graph.aget_state(
                {"configurable": {"thread_id": str(operation_id)}}
            )
            assert snapshot.values["decision"] == "approved"
            # Complete this action so the next integration scenario owns the queue.
            dispatcher = OutboxDispatcher(
                url, {"slack": FakeProvider(["receipt-initial"])}
            )
            assert await dispatcher.run_once()

    asyncio.run(scenario())


class FakeEmbedder:
    async def embed_query(self, text: str) -> list[float]:
        return [0.1] * 2048

    async def embed_passage(self, text: str) -> list[float]:
        return [0.1] * 2048


class FakeProvider:
    def __init__(self, outcomes: list) -> None:
        self.outcomes = outcomes
        self.keys = []

    async def send(self, draft, key: str) -> Receipt:
        self.keys.append(key)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return Receipt(outcome)


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs PostgreSQL")
def test_ingestion_retry_idempotency_and_unknown_reconciliation() -> None:
    async def scenario() -> None:
        url = os.environ["TEST_DATABASE_URL"]
        schema = Path(__file__).parents[1] / "app" / "schema.sql"
        async with await psycopg.AsyncConnection.connect(url) as conn:
            await conn.execute(schema.read_text(encoding="utf-8"))
        tenant_id, requester_id, reviewer_id, admin_id = (
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
        )
        async with await psycopg.AsyncConnection.connect(url) as conn:
            for user_id, role in (
                (requester_id, "requester"),
                (reviewer_id, "reviewer"),
                (admin_id, "admin"),
            ):
                await conn.execute(
                    """INSERT INTO users (id, tenant_id, identity_subject, role)
                       VALUES (%s, %s, %s, %s)""",
                    (user_id, tenant_id, str(user_id), role),
                )
        embedder = FakeEmbedder()
        ingestor = KnowledgeIngestor(url, embedder)
        document = KnowledgeInput(
            source="runbook", content="Escalate billing disputes.", ingestion_version=1
        )
        document_id = await ingestor.ingest(tenant_id, document)
        assert await ingestor.ingest(tenant_id, document) == document_id
        evidence = await PgVectorRetriever(url, embedder).search(
            str(tenant_id), "billing"
        )
        assert evidence[0].source == "runbook"
        await CustomerAccountStore(url).upsert(
            tenant_id,
            CustomerAccountInput(customer_id="c-real", account_status="active"),
        )
        customer_adapter = PostgresCustomerDataAdapter(url)
        assert (
            await customer_adapter.get_customer(str(tenant_id), "c-real")
        ).account_status == "active"
        assert await customer_adapter.get_customer(str(uuid4()), "c-real") is None
        async with AsyncPostgresSaver.from_conn_string(url) as checkpointer:
            await checkpointer.setup()
            graph = build_graph(
                PgVectorRetriever(url, embedder), customer_adapter, checkpointer
            )
            service = OperationService(url, graph)

            async def approved_operation() -> tuple:
                operation_id = await service.create(
                    Actor(requester_id, tenant_id, "requester"),
                    OperationRequest(
                        request_text="Escalate billing case", customer_id="c-real"
                    ),
                )
                snapshot = await graph.aget_state(
                    {"configurable": {"thread_id": str(operation_id)}}
                )
                assert snapshot.values["customer_status"] == "active"
                assert (
                    snapshot.values["recommendation"]["evidence"][0]["source"]
                    == "runbook"
                )
                async with await psycopg.AsyncConnection.connect(url) as conn:
                    cursor = await conn.execute(
                        "SELECT payload_hash FROM action_drafts WHERE operation_id = %s",
                        (operation_id,),
                    )
                    draft_hash = (await cursor.fetchone())[0]
                await service.decide(
                    Actor(reviewer_id, tenant_id, "reviewer"),
                    operation_id,
                    ApprovalDecision(decision="approved", draft_hash=draft_hash),
                )
                return operation_id, draft_hash

            operation_id, draft_hash = await approved_operation()
            provider = FakeProvider([RetryableDeliveryError("rate_limit"), "receipt-1"])
            dispatcher = OutboxDispatcher(url, {"slack": provider})
            assert await dispatcher.run_once()
            async with await psycopg.AsyncConnection.connect(url) as conn:
                cursor = await conn.execute(
                    "SELECT status, attempt_count FROM outbox_actions WHERE operation_id = %s",
                    (operation_id,),
                )
                assert await cursor.fetchone() == ("retry_pending", 1)
                await conn.execute(
                    "UPDATE outbox_actions SET next_attempt_at = now() WHERE operation_id = %s",
                    (operation_id,),
                )
            assert await dispatcher.run_once()
            assert not await dispatcher.run_once()
            assert provider.keys == [f"{operation_id}:1:{draft_hash}"] * 2
            async with await psycopg.AsyncConnection.connect(url) as conn:
                cursor = await conn.execute(
                    """SELECT status, provider_receipt_id, attempt_count
                       FROM outbox_actions WHERE operation_id = %s""",
                    (operation_id,),
                )
                assert await cursor.fetchone() == ("sent", "receipt-1", 2)

            unknown_operation, _ = await approved_operation()
            unknown_provider = FakeProvider([UnknownDeliveryOutcome("timeout")])
            dispatcher = OutboxDispatcher(url, {"slack": unknown_provider})
            assert await dispatcher.run_once()
            assert not await dispatcher.run_once()
            async with await psycopg.AsyncConnection.connect(url) as conn:
                cursor = await conn.execute(
                    "SELECT id, status FROM outbox_actions WHERE operation_id = %s",
                    (unknown_operation,),
                )
                action_id, state = await cursor.fetchone()
                assert state == "unknown"
            await dispatcher.reconcile(
                Actor(admin_id, tenant_id, "admin"),
                action_id,
                sent=True,
                receipt_id="manual-confirmed-id",
                evidence="Provider dashboard receipt",
            )
            assert not await dispatcher.run_once()
            assert len(unknown_provider.keys) == 1
            async with await psycopg.AsyncConnection.connect(url) as conn:
                cursor = await conn.execute(
                    "SELECT status, provider_receipt_id FROM outbox_actions WHERE id = %s",
                    (action_id,),
                )
                assert await cursor.fetchone() == ("sent", "manual-confirmed-id")

            crashed_operation, _ = await approved_operation()
            claimed = await dispatcher._claim()
            assert claimed.operation_id == crashed_operation
            async with await psycopg.AsyncConnection.connect(url) as conn:
                await conn.execute(
                    """UPDATE outbox_actions SET claimed_at = now() - interval '5 minutes'
                       WHERE id = %s""",
                    (claimed.id,),
                )
            assert await dispatcher.mark_stale_unknown() == 1
            assert not await dispatcher.run_once()
            async with await psycopg.AsyncConnection.connect(url) as conn:
                cursor = await conn.execute(
                    "SELECT status FROM outbox_actions WHERE id = %s", (claimed.id,)
                )
                assert (await cursor.fetchone())[0] == "unknown"

    asyncio.run(scenario())
