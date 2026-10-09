"""Durable drafting graph. External delivery is deliberately outside the graph."""

import hashlib
import json
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.adapters import CustomerDataAdapter
from app.models import ActionDraft, ApprovalDecision, Evidence, Recommendation


class KnowledgeRetriever(Protocol):
    async def search(self, tenant_id: str, query: str) -> list[Evidence]: ...


class GraphState(TypedDict, total=False):
    tenant_id: str
    request_text: str
    customer_id: str | None
    evidence: list[dict[str, str]]
    customer_status: str | None
    recommendation: dict
    draft: dict
    draft_hash: str
    decision: str


def draft_hash(draft: dict) -> str:
    canonical = json.dumps(draft, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_graph(
    retriever: KnowledgeRetriever, customer_data: CustomerDataAdapter, checkpointer
):
    async def retrieve(state: GraphState) -> GraphState:
        evidence = await retriever.search(state["tenant_id"], state["request_text"])
        return {"evidence": [item.model_dump() for item in evidence]}

    async def inspect(state: GraphState) -> GraphState:
        customer_id = state.get("customer_id")
        record = await customer_data.get_customer(customer_id) if customer_id else None
        return {"customer_status": record.account_status if record else None}

    def draft(state: GraphState) -> GraphState:
        evidence = [Evidence.model_validate(item) for item in state["evidence"]]
        status = state.get("customer_status")
        summary = f"Review the operations request for customer {state.get('customer_id') or 'unknown'}."
        uncertainty = "Human review required; no verified customer status."
        if status:
            uncertainty = "Human review required before any external action."
        recommendation = Recommendation(
            summary=summary,
            evidence=evidence,
            uncertainty=uncertainty,
            risk_level="medium" if status else "high",
        )
        body = f"Request: {state['request_text']}\nCustomer status: {status or 'unknown'}\nReview required."
        action = ActionDraft(
            provider="slack", destination="operations-review", body=body
        )
        payload = action.model_dump(mode="json")
        return {
            "recommendation": recommendation.model_dump(mode="json"),
            "draft": payload,
            "draft_hash": draft_hash(payload),
        }

    def await_approval(state: GraphState) -> GraphState:
        answer = interrupt({"draft": state["draft"], "draft_hash": state["draft_hash"]})
        decision = ApprovalDecision.model_validate(answer)
        if decision.draft_hash != state["draft_hash"]:
            raise ValueError("Approval targets a stale draft")
        return {"decision": decision.decision}

    builder = StateGraph(GraphState)
    builder.add_node("retrieve", retrieve)
    builder.add_node("inspect", inspect)
    builder.add_node("draft", draft)
    builder.add_node("await_approval", await_approval)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "inspect")
    builder.add_edge("inspect", "draft")
    builder.add_edge("draft", "await_approval")
    builder.add_edge("await_approval", END)
    return builder.compile(checkpointer=checkpointer)
