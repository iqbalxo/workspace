from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field, TypeAdapter

from support_pipeline.artifact_store import JsonArtifactStore
from support_pipeline.types import DraftResponse, ResponseCheck, RetrievalResult, Ticket, TriageResult


class ResponseCheckRules(BaseModel):
    banned_phrases: list[str] = Field(default_factory=list)
    min_reply_chars: int = 40
    require_escalation_note_when_escalated: bool = True


class ResponseCheckInput(BaseModel):
    ticket: Ticket
    triage: TriageResult
    retrieval: RetrievalResult
    draft: DraftResponse


@dataclass(frozen=True)
class ResponseCheckStageResult:
    records: list[ResponseCheck]


class ResponseCheckRulesLoader:
    _adapter = TypeAdapter(ResponseCheckRules)

    @classmethod
    def from_file(cls, path: Path) -> ResponseCheckRules:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls._adapter.validate_python(data)


class ResponseCheckStageRunner(Protocol):
    def run(
        self,
        inputs: list[ResponseCheckInput],
        rules: ResponseCheckRules,
        checks_artifact_path: Path,
    ) -> ResponseCheckStageResult:
        ...


class DeterministicResponseCheckRunner:
    def __init__(self, artifact_store: JsonArtifactStore) -> None:
        self._artifact_store = artifact_store

    def run(
        self,
        inputs: list[ResponseCheckInput],
        rules: ResponseCheckRules,
        checks_artifact_path: Path,
    ) -> ResponseCheckStageResult:
        records: list[ResponseCheck] = []
        for item in inputs:
            issues = self._collect_issues(item=item, rules=rules)
            records.append(
                ResponseCheck(
                    ticket_id=item.ticket.ticket_id,
                    passed=len(issues) == 0,
                    issues=issues,
                )
            )

        self._artifact_store.write_checks(checks_artifact_path, records)
        return ResponseCheckStageResult(records=records)

    def _collect_issues(self, item: ResponseCheckInput, rules: ResponseCheckRules) -> list[str]:
        issues: list[str] = []
        reply_text = item.draft.reply.strip()
        citations = item.draft.cited_policy_ids
        retrieved_ids = set(item.retrieval.retrieved_policy_ids)

        if not citations:
            issues.append("missing_policy_citations")
        else:
            invalid = sorted({cid for cid in citations if cid not in retrieved_ids})
            if invalid:
                issues.append(f"citations_outside_retrieved_set:{','.join(invalid)}")

        if len(reply_text) < rules.min_reply_chars:
            issues.append("reply_too_short")

        lowered = reply_text.lower()
        matched_phrases = [
            phrase for phrase in rules.banned_phrases if phrase.lower() in lowered
        ]
        if matched_phrases:
            issues.append(f"banned_promise_language:{','.join(matched_phrases)}")

        escalation_note = (item.draft.escalation_note or "").strip()
        requires_escalation = item.triage.should_escalate
        mentions_escalation = self._mentions_escalation(reply_text)

        if requires_escalation:
            if rules.require_escalation_note_when_escalated and not escalation_note:
                issues.append("missing_escalation_note_for_escalated_ticket")
            if not mentions_escalation:
                issues.append("escalation_mismatch_missing_next_step")
        else:
            if escalation_note:
                issues.append("escalation_mismatch_unexpected_escalation_note")

        return issues

    @staticmethod
    def _mentions_escalation(reply_text: str) -> bool:
        lowered = reply_text.lower()
        escalation_markers = (
            "escalat",
            "investigat",
            "review",
            "specialist",
            "team will",
            "next step",
        )
        return any(marker in lowered for marker in escalation_markers)
