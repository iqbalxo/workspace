from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

from support_pipeline.types import (
    DraftResponse,
    LLMCallRecord,
    PipelineStage,
    Policy,
    ResponseCheck,
    RetrievalResult,
    ReviewResult,
    Ticket,
    TriageResult,
)


class ArtifactStore(Protocol):
    def read_tickets(self, path: Path) -> list[Ticket]:
        ...

    def read_policies(self, path: Path) -> list[Policy]:
        ...

    def write_triage(self, path: Path, records: Sequence[TriageResult]) -> None:
        ...

    def write_retrieval(self, path: Path, records: Sequence[RetrievalResult]) -> None:
        ...

    def write_drafts(self, path: Path, records: Sequence[DraftResponse]) -> None:
        ...

    def write_checks(self, path: Path, records: Sequence[ResponseCheck]) -> None:
        ...

    def write_review_results(self, path: Path, records: Sequence[ReviewResult]) -> None:
        ...

    def write_final(self, path: Path, records: Sequence[object]) -> None:
        ...

    def append_llm_call(self, path: Path, record: LLMCallRecord) -> None:
        ...


class StageTracker(Protocol):
    @property
    def current_stage(self) -> PipelineStage:
        ...

    def transition_to(self, next_stage: PipelineStage) -> None:
        ...


class TriageService(Protocol):
    def triage_ticket(self, ticket: Ticket) -> TriageResult:
        ...


class RetrievalService(Protocol):
    def retrieve_for_ticket(self, ticket: Ticket, policies: Sequence[Policy]) -> RetrievalResult:
        ...


class DraftingService(Protocol):
    def draft_response(
        self,
        ticket: Ticket,
        triage: TriageResult,
        retrieved_policies: Sequence[Policy],
    ) -> DraftResponse:
        ...


class CheckService(Protocol):
    def check_draft(
        self,
        ticket: Ticket,
        triage: TriageResult,
        retrieval: RetrievalResult,
        draft: DraftResponse,
    ) -> ResponseCheck:
        ...


class ReviewService(Protocol):
    def review_draft(
        self,
        ticket: Ticket,
        triage: TriageResult,
        retrieval: RetrievalResult,
        draft: DraftResponse,
    ) -> ReviewResult:
        ...
