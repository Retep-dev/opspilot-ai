"""Validated inputs and agent output contracts."""

from typing import Literal

from pydantic import BaseModel, Field


class OperationRequest(BaseModel):
    request_text: str = Field(min_length=1, max_length=4000)
    customer_id: str | None = Field(default=None, max_length=128)


class Evidence(BaseModel):
    source: str
    excerpt: str


class Recommendation(BaseModel):
    summary: str
    evidence: list[Evidence]
    uncertainty: str
    risk_level: Literal["low", "medium", "high"]


class ActionDraft(BaseModel):
    provider: Literal["slack", "email"]
    destination: str
    subject: str | None = None
    body: str


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    draft_hash: str
    reason: str | None = None


class GeneratedDraft(BaseModel):
    recommendation: Recommendation
    draft: ActionDraft
