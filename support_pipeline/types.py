from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class PipelineStage(str, Enum):
    INIT = "INIT"
    INPUTS_LOADED = "INPUTS_LOADED"
    TICKETS_PARSED = "TICKETS_PARSED"
    KB_INDEXED = "KB_INDEXED"
    TICKET_TRIAGED = "TICKET_TRIAGED"
    EVIDENCE_RETRIEVED = "EVIDENCE_RETRIEVED"
    RESPONSE_DRAFTED = "RESPONSE_DRAFTED"
    RESPONSE_CHECKED = "RESPONSE_CHECKED"
    RESPONSE_FINALISED = "RESPONSE_FINALISED"


class Ticket(BaseModel):
    ticket_id: str
    customer_name: str
    subject: str
    message: str
    language: str


class Policy(BaseModel):
    policy_id: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)


Category = Literal[
    "withdrawal_issue",
    "payment_issue",
    "verification_issue",
    "account_closure",
    "other",
]
Priority = Literal["high", "medium", "low"]
FinalStatus = Literal["ready", "needs_human_review"]
LLMStage = Literal["triage", "drafting", "review"]


class TriageResult(BaseModel):
    ticket_id: str
    category: Category
    priority: Priority
    should_escalate: bool
    reason: str
    missing_information: list[str] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    ticket_id: str
    retrieved_policy_ids: list[str] = Field(default_factory=list)
    ranking_explanation: str


class DraftResponse(BaseModel):
    ticket_id: str
    subject: str
    reply: str
    cited_policy_ids: list[str] = Field(default_factory=list)
    escalation_note: str | None


class ResponseCheck(BaseModel):
    ticket_id: str
    passed: bool
    issues: list[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    ticket_id: str
    approved: bool
    issues: list[str] = Field(default_factory=list)
    suggested_fix: str


class FinalResponse(BaseModel):
    ticket_id: str
    category: str
    priority: str
    final_status: FinalStatus
    reply: str
    supporting_policy_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class LLMCallRecord(BaseModel):
    stage: LLMStage
    ticket_id: str
    timestamp: datetime
    provider: str
    model: str
    prompt_hash: str
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifact: str
