from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from support_pipeline.artifact_store import JsonArtifactStore
from support_pipeline.stage_tracker import OrderedStageTracker
from support_pipeline.triage import TriageRulesLoader, TriageStageRunner
from support_pipeline.types import PipelineStage, Policy, Ticket


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
    ) -> None:
        rules = TriageRulesLoader.from_file(rules_path)
        self._triage_runner.run(
            tickets=tickets,
            rules=rules,
            triage_artifact_path=triage_artifact_path,
            llm_calls_artifact_path=llm_calls_artifact_path,
            input_artifacts=input_artifacts,
        )
        self._stage_tracker.transition_to(PipelineStage.TICKET_TRIAGED)
