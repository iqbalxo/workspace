from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field, TypeAdapter

from support_pipeline.artifact_store import JsonArtifactStore
from support_pipeline.types import DraftResponse, FinalResponse, ResponseCheck, RetrievalResult, TriageResult


class FinalizationRules(BaseModel):
    allow_ready_when_escalated_if_note_present: bool = True
    require_supporting_policy_ids: bool = True
    include_check_issues_in_notes: bool = True


class FinalizationInput(BaseModel):
    triage: TriageResult
    retrieval: RetrievalResult
    draft: DraftResponse
    check: ResponseCheck


@dataclass(frozen=True)
class FinalizationStageResult:
    records: list[FinalResponse]


class FinalizationRulesLoader:
    _adapter = TypeAdapter(FinalizationRules)

    @classmethod
    def from_file(cls, path: Path) -> FinalizationRules:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls._adapter.validate_python(data)


class FinalizationStageRunner(Protocol):
    def run(
        self,
        inputs: list[FinalizationInput],
        rules: FinalizationRules,
        final_artifact_path: Path,
    ) -> FinalizationStageResult:
        ...


class DeterministicFinalizationRunner:
    def __init__(self, artifact_store: JsonArtifactStore) -> None:
        self._artifact_store = artifact_store

    def run(
        self,
        inputs: list[FinalizationInput],
        rules: FinalizationRules,
        final_artifact_path: Path,
    ) -> FinalizationStageResult:
        records: list[FinalResponse] = []
        for item in inputs:
            final_status = self._determine_final_status(item=item, rules=rules)
            supporting_policy_ids = self._supporting_policy_ids(item=item, rules=rules)
            notes = self._build_notes(item=item, rules=rules, final_status=final_status)
            records.append(
                FinalResponse(
                    ticket_id=item.triage.ticket_id,
                    category=item.triage.category,
                    priority=item.triage.priority,
                    final_status=final_status,
                    reply=item.draft.reply,
                    supporting_policy_ids=supporting_policy_ids,
                    notes=notes,
                )
            )

        self._artifact_store.write_final(final_artifact_path, records)
        return FinalizationStageResult(records=records)

    def _determine_final_status(self, item: FinalizationInput, rules: FinalizationRules) -> str:
        if not item.check.passed:
            return "needs_human_review"

        if not item.triage.should_escalate:
            return "ready"

        if not rules.allow_ready_when_escalated_if_note_present:
            return "needs_human_review"

        escalation_note = (item.draft.escalation_note or "").strip()
        if not escalation_note:
            return "needs_human_review"

        if not self._mentions_escalation(item.draft.reply):
            return "needs_human_review"

        return "ready"

    def _supporting_policy_ids(self, item: FinalizationInput, rules: FinalizationRules) -> list[str]:
        retrieved_ids = item.retrieval.retrieved_policy_ids
        cited_ids = item.draft.cited_policy_ids
        retrieved_set = set(retrieved_ids)
        filtered = [policy_id for policy_id in cited_ids if policy_id in retrieved_set]
        if filtered:
            return filtered

        if rules.require_supporting_policy_ids:
            return retrieved_ids[:1]

        return []

    def _build_notes(
        self,
        item: FinalizationInput,
        rules: FinalizationRules,
        final_status: str,
    ) -> list[str]:
        notes = [f"triage_reason:{item.triage.reason}"]
        if item.triage.should_escalate:
            notes.append("triage_requires_escalation")
        if item.draft.escalation_note:
            notes.append(f"draft_escalation_note:{item.draft.escalation_note}")
        if rules.include_check_issues_in_notes and item.check.issues:
            notes.extend(f"check_issue:{issue}" for issue in item.check.issues)
        notes.append(f"check_passed:{item.check.passed}")
        notes.append(f"final_status_reason:{final_status}")
        return notes

    @staticmethod
    def _mentions_escalation(reply_text: str) -> bool:
        lowered = reply_text.lower()
        markers = (
            "escalat",
            "investigat",
            "specialist",
            "team",
            "review",
            "next step",
        )
        return any(marker in lowered for marker in markers)
