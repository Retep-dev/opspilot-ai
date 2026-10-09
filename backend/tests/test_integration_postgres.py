"""Runs against a disposable pgvector database in CI."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.adapters import CustomerRecord, MockCustomerDataAdapter
from app.graph import build_graph
from app.models import ApprovalDecision, Evidence, OperationRequest
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

    asyncio.run(scenario())
