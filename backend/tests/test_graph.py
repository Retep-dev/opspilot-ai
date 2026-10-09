import asyncio

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.adapters import CustomerRecord, MockCustomerDataAdapter
from app.graph import build_graph
from app.models import Evidence


class FakeRetriever:
    async def search(self, tenant_id: str, query: str) -> list[Evidence]:
        assert tenant_id == "tenant-1"
        return [Evidence(source="runbook-1", excerpt="Escalate billing disputes")]


def test_graph_interrupts_and_resumes_with_exact_draft_hash() -> None:
    async def scenario() -> None:
        graph = build_graph(
            FakeRetriever(),
            MockCustomerDataAdapter({"c-1": CustomerRecord("c-1", "active")}),
            MemorySaver(),
        )
        config = {"configurable": {"thread_id": "op-1"}}
        result = await graph.ainvoke(
            {
                "tenant_id": "tenant-1",
                "request_text": "Billing dispute",
                "customer_id": "c-1",
            },
            config,
        )
        assert "__interrupt__" in result
        snapshot = await graph.aget_state(config)
        assert snapshot.next == ("await_approval",)
        assert snapshot.values["evidence"][0]["source"] == "runbook-1"
        assert snapshot.values["customer_status"] == "active"
        assert snapshot.values["draft"]["provider"] == "slack"
        resumed = await graph.ainvoke(
            Command(
                resume={
                    "decision": "approved",
                    "draft_hash": snapshot.values["draft_hash"],
                }
            ),
            config,
        )
        assert resumed["decision"] == "approved"
        assert (await graph.aget_state(config)).next == ()

    asyncio.run(scenario())


def test_graph_rejects_stale_draft_hash() -> None:
    async def scenario() -> None:
        graph = build_graph(FakeRetriever(), MockCustomerDataAdapter(), MemorySaver())
        config = {"configurable": {"thread_id": "op-2"}}
        await graph.ainvoke(
            {
                "tenant_id": "tenant-1",
                "request_text": "Check account",
                "customer_id": None,
            },
            config,
        )
        try:
            await graph.ainvoke(
                Command(resume={"decision": "approved", "draft_hash": "wrong"}), config
            )
        except ValueError as error:
            assert "stale draft" in str(error)
        else:
            raise AssertionError("stale approval must fail")

    asyncio.run(scenario())
