from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from support_pipeline.artifact_store import JsonArtifactStore
from support_pipeline.drafting import DraftingInput, DraftingRulesLoader, DraftingStageRunner
from support_pipeline.retrieval import DeterministicRetrievalService, RetrievalStageResult
from support_pipeline.response_checks import (
    ResponseCheckInput,
    ResponseCheckRulesLoader,
    ResponseCheckStageRunner,
)
from support_pipeline.stage_tracker import OrderedStageTracker
from support_pipeline.triage import TriageRulesLoader, TriageStageRunner
from support_pipeline.types import (
    DraftResponse,
    PipelineStage,
    Policy,
    RetrievalResult,
    Ticket,
    TriageResult,
)


@dataclass(frozen=True)
class BootstrapArtifacts:
    tickets: list[Ticket]
    policies: list[Policy]
    policy_index: dict[str, Policy]


class PhaseOneBootstrapRunner:
    """Phase 1 runner that validates inputs and builds deterministic KB index."""

    def __init__(
        self,
        artifact_store: JsonArtifactStore,
        stage_tracker: OrderedStageTracker,
    ) -> None:
        self._artifact_store = artifact_store
        self._stage_tracker = stage_tracker

    def run(self, tickets_path: Path, policy_kb_path: Path) -> BootstrapArtifacts:
        tickets = self._artifact_store.read_tickets(tickets_path)
        policies = self._artifact_store.read_policies(policy_kb_path)

        self._stage_tracker.transition_to(PipelineStage.INPUTS_LOADED)
        self._stage_tracker.transition_to(PipelineStage.TICKETS_PARSED)

        policy_index = self._build_policy_index(policies)
        self._stage_tracker.transition_to(PipelineStage.KB_INDEXED)

        return BootstrapArtifacts(
            tickets=tickets,
            policies=policies,
            policy_index=policy_index,
        )

    @staticmethod
    def _build_policy_index(policies: list[Policy]) -> dict[str, Policy]:
        index: dict[str, Policy] = {}
        for policy in sorted(policies, key=lambda item: item.policy_id):
            index[policy.policy_id] = policy
        return index


class PhaseTwoTriageRunner:
    """Phase 2 runner that executes one triage LLM call per ticket."""

    def __init__(
        self,
        stage_tracker: OrderedStageTracker,
        triage_runner: TriageStageRunner,
    ) -> None:
        self._stage_tracker = stage_tracker
        self._triage_runner = triage_runner

    def run(
        self,
        tickets: list[Ticket],
        rules_path: Path,
        triage_artifact_path: Path,
        llm_calls_artifact_path: Path,
        input_artifacts: list[str],
    ) -> list[TriageResult]:
        rules = TriageRulesLoader.from_file(rules_path)
        triage_output = self._triage_runner.run(
            tickets=tickets,
            rules=rules,
            triage_artifact_path=triage_artifact_path,
            llm_calls_artifact_path=llm_calls_artifact_path,
            input_artifacts=input_artifacts,
        )
        self._stage_tracker.transition_to(PipelineStage.TICKET_TRIAGED)
        return triage_output.records


class PhaseThreeRetrievalRunner:
    """Phase 3 runner that performs deterministic policy retrieval."""

    def __init__(
        self,
        stage_tracker: OrderedStageTracker,
        artifact_store: JsonArtifactStore,
        retrieval_service: DeterministicRetrievalService,
    ) -> None:
        self._stage_tracker = stage_tracker
        self._artifact_store = artifact_store
        self._retrieval_service = retrieval_service

    def run(
        self,
        tickets: list[Ticket],
        triage_records: list[TriageResult],
        policies: list[Policy],
        retrieval_artifact_path: Path,
    ) -> RetrievalStageResult:
        triage_by_ticket = {item.ticket_id: item for item in triage_records}
        records = []
        for ticket in tickets:
            triage = triage_by_ticket[ticket.ticket_id]
            records.append(
                self._retrieval_service.retrieve_for_ticket(
                    ticket=ticket,
                    triage=triage,
                    policies=policies,
                )
            )

        self._artifact_store.write_retrieval(retrieval_artifact_path, records)
        self._stage_tracker.transition_to(PipelineStage.EVIDENCE_RETRIEVED)
        return RetrievalStageResult(records=records)


class PhaseFourDraftingRunner:
    """Phase 4 runner that drafts customer responses via one LLM call per ticket."""

    def __init__(
        self,
        stage_tracker: OrderedStageTracker,
        drafting_runner: DraftingStageRunner,
    ) -> None:
        self._stage_tracker = stage_tracker
        self._drafting_runner = drafting_runner

    def run(
        self,
        tickets: list[Ticket],
        triage_records: list[TriageResult],
        retrieval_records: list[RetrievalResult],
        policy_index: dict[str, Policy],
        rules_path: Path,
        drafts_artifact_path: Path,
        llm_calls_artifact_path: Path,
        input_artifacts: list[str],
    ) -> list[DraftResponse]:
        rules = DraftingRulesLoader.from_file(rules_path)
        triage_by_ticket = {item.ticket_id: item for item in triage_records}
        retrieval_by_ticket = {item.ticket_id: item for item in retrieval_records}
        drafting_inputs: list[DraftingInput] = []

        for ticket in tickets:
            triage = triage_by_ticket[ticket.ticket_id]
            retrieval = retrieval_by_ticket[ticket.ticket_id]
            retrieved_policies = [
                policy_index[policy_id]
                for policy_id in retrieval.retrieved_policy_ids
                if policy_id in policy_index
            ]
            drafting_inputs.append(
                DraftingInput(
                    ticket=ticket,
                    triage=triage,
                    retrieved_policies=retrieved_policies,
                )
            )

        drafting_result = self._drafting_runner.run(
            inputs=drafting_inputs,
            rules=rules,
            draft_artifact_path=drafts_artifact_path,
            llm_calls_artifact_path=llm_calls_artifact_path,
            input_artifacts=input_artifacts,
        )
        self._stage_tracker.transition_to(PipelineStage.RESPONSE_DRAFTED)
        return drafting_result.records


class PhaseFiveResponseCheckRunner:
    """Phase 5 runner for deterministic validation over drafted replies."""

    def __init__(
        self,
        stage_tracker: OrderedStageTracker,
        check_runner: ResponseCheckStageRunner,
    ) -> None:
        self._stage_tracker = stage_tracker
        self._check_runner = check_runner

    def run(
        self,
        tickets: list[Ticket],
        triage_records: list[TriageResult],
        retrieval_records: list[RetrievalResult],
        draft_records: list[DraftResponse],
        rules_path: Path,
        checks_artifact_path: Path,
    ) -> None:
        rules = ResponseCheckRulesLoader.from_file(rules_path)
        triage_by_ticket = {item.ticket_id: item for item in triage_records}
        retrieval_by_ticket = {item.ticket_id: item for item in retrieval_records}
        draft_by_ticket = {item.ticket_id: item for item in draft_records}

        inputs: list[ResponseCheckInput] = []
        for ticket in tickets:
            inputs.append(
                ResponseCheckInput(
                    ticket=ticket,
                    triage=triage_by_ticket[ticket.ticket_id],
                    retrieval=retrieval_by_ticket[ticket.ticket_id],
                    draft=draft_by_ticket[ticket.ticket_id],
                )
            )

        self._check_runner.run(
            inputs=inputs,
            rules=rules,
            checks_artifact_path=checks_artifact_path,
        )
        self._stage_tracker.transition_to(PipelineStage.RESPONSE_CHECKED)
