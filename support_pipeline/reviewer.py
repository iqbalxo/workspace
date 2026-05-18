from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, TypeAdapter

from support_pipeline.artifact_store import JsonArtifactStore
from support_pipeline.settings import OpenRouterSettings
from support_pipeline.types import LLMCallRecord
from support_pipeline.types import DraftResponse, RetrievalResult, ReviewResult, Ticket, TriageResult


class ReviewerRules(BaseModel):
    grounding_required: bool = True
    escalation_alignment_required: bool = True
    clarity_required: bool = True
    safety_required: bool = True


class ReviewerInput(BaseModel):
    ticket: Ticket
    triage: TriageResult
    retrieval: RetrievalResult
    draft: DraftResponse


@dataclass(frozen=True)
class ReviewerStageResult:
    records: list[ReviewResult]


class ReviewerRulesLoader:
    _adapter = TypeAdapter(ReviewerRules)

    @classmethod
    def from_file(cls, path: Path) -> ReviewerRules:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls._adapter.validate_python(data)


class ReviewerStageRunner(Protocol):
    def run(
        self,
        inputs: list[ReviewerInput],
        rules: ReviewerRules,
        review_artifact_path: Path,
        llm_calls_artifact_path: Path,
        input_artifacts: list[str],
    ) -> ReviewerStageResult:
        ...


class OpenRouterReviewerService:
    def __init__(self, settings: OpenRouterSettings, timeout_seconds: float = 60.0) -> None:
        self._settings = settings
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        return self._settings.model

    def review_draft(
        self,
        ticket: Ticket,
        triage: TriageResult,
        retrieval: RetrievalResult,
        draft: DraftResponse,
        rules: ReviewerRules,
    ) -> tuple[ReviewResult, str]:
        prompt = self._build_user_prompt(
            ticket=ticket,
            triage=triage,
            retrieval=retrieval,
            draft=draft,
            rules=rules,
        )
        payload = {
            "model": self._settings.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": prompt},
            ],
        }
        response_json = self._post_chat_completion(payload)
        content = self._extract_message_content(response_json)
        review = self._parse_review(content)
        review.ticket_id = ticket.ticket_id
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return review, prompt_hash

    def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._settings.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self._timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _extract_message_content(response_json: dict[str, Any]) -> str:
        choices = response_json.get("choices")
        if not choices:
            raise ValueError("OpenRouter response missing choices.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("OpenRouter response missing message content.")
        return content

    @staticmethod
    def _parse_review(raw_content: str) -> ReviewResult:
        normalized = raw_content.strip()
        if normalized.startswith("```"):
            lines = normalized.splitlines()
            if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
                normalized = "\n".join(lines[1:-1]).strip()
                if normalized.lower().startswith("json"):
                    normalized = normalized[4:].strip()
        parsed = json.loads(normalized)
        return ReviewResult.model_validate(parsed)

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are a support reply reviewer. "
            "Evaluate grounding, safety, clarity, and escalation handling. "
            "Return JSON only with keys: ticket_id, approved, issues, suggested_fix."
        )

    @staticmethod
    def _build_user_prompt(
        ticket: Ticket,
        triage: TriageResult,
        retrieval: RetrievalResult,
        draft: DraftResponse,
        rules: ReviewerRules,
    ) -> str:
        return (
            "Review this drafted support response.\n"
            "Determine if it is grounded in retrieved policy IDs, safe, clear, and escalation-aligned.\n\n"
            "Rules:\n"
            f"- grounding_required: {rules.grounding_required}\n"
            f"- escalation_alignment_required: {rules.escalation_alignment_required}\n"
            f"- clarity_required: {rules.clarity_required}\n"
            f"- safety_required: {rules.safety_required}\n\n"
            "Ticket:\n"
            f"- ticket_id: {ticket.ticket_id}\n"
            f"- subject: {ticket.subject}\n"
            f"- message: {ticket.message}\n\n"
            "Triage:\n"
            f"- category: {triage.category}\n"
            f"- priority: {triage.priority}\n"
            f"- should_escalate: {triage.should_escalate}\n"
            f"- reason: {triage.reason}\n\n"
            "Retrieved policy IDs:\n"
            f"- {', '.join(retrieval.retrieved_policy_ids)}\n\n"
            "Draft:\n"
            f"- subject: {draft.subject}\n"
            f"- reply: {draft.reply}\n"
            f"- cited_policy_ids: {', '.join(draft.cited_policy_ids)}\n"
            f"- escalation_note: {draft.escalation_note}\n\n"
            "Return JSON with:\n"
            "{\n"
            '  "ticket_id": "string",\n'
            '  "approved": true,\n'
            '  "issues": ["string"],\n'
            '  "suggested_fix": "string"\n'
            "}"
        )


class OpenRouterReviewerStageRunner:
    def __init__(
        self,
        service: OpenRouterReviewerService,
        artifact_store: JsonArtifactStore,
    ) -> None:
        self._service = service
        self._artifact_store = artifact_store

    def run(
        self,
        inputs: list[ReviewerInput],
        rules: ReviewerRules,
        review_artifact_path: Path,
        llm_calls_artifact_path: Path,
        input_artifacts: list[str],
    ) -> ReviewerStageResult:
        records: list[ReviewResult] = []
        for item in inputs:
            review, prompt_hash = self._service.review_draft(
                ticket=item.ticket,
                triage=item.triage,
                retrieval=item.retrieval,
                draft=item.draft,
                rules=rules,
            )
            records.append(review)
            self._artifact_store.append_llm_call(
                llm_calls_artifact_path,
                LLMCallRecord(
                    stage="review",
                    ticket_id=item.ticket.ticket_id,
                    timestamp=datetime.now(timezone.utc),
                    provider="openrouter",
                    model=self._service.model,
                    prompt_hash=prompt_hash,
                    input_artifacts=input_artifacts,
                    output_artifact=str(review_artifact_path),
                ),
            )

        self._artifact_store.write_review_results(review_artifact_path, records)
        return ReviewerStageResult(records=records)
