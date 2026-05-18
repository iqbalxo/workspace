from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field
from pydantic import TypeAdapter

from support_pipeline.artifact_store import JsonArtifactStore
from support_pipeline.settings import OpenRouterSettings
from support_pipeline.types import LLMCallRecord
from support_pipeline.types import DraftResponse, Policy, Ticket, TriageResult


class DraftingRules(BaseModel):
    tone_requirements: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)
    required_output_keys: list[str] = Field(default_factory=list)
    enforce_citation: bool = True


class DraftingInput(BaseModel):
    ticket: Ticket
    triage: TriageResult
    retrieved_policies: list[Policy] = Field(default_factory=list)


@dataclass(frozen=True)
class DraftingStageResult:
    records: list[DraftResponse]


class DraftingRulesLoader:
    _adapter = TypeAdapter(DraftingRules)

    @classmethod
    def from_file(cls, path: Path) -> DraftingRules:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls._adapter.validate_python(data)


class OpenRouterDraftingService:
    def __init__(self, settings: OpenRouterSettings, timeout_seconds: float = 60.0) -> None:
        self._settings = settings
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        return self._settings.model

    def draft_response(
        self,
        ticket: Ticket,
        triage: TriageResult,
        retrieved_policies: list[Policy],
        rules: DraftingRules,
    ) -> tuple[DraftResponse, str]:
        prompt = self._build_user_prompt(
            ticket=ticket,
            triage=triage,
            retrieved_policies=retrieved_policies,
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
        draft = self._parse_draft(content)
        draft.ticket_id = ticket.ticket_id
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return draft, prompt_hash

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
    def _parse_draft(raw_content: str) -> DraftResponse:
        normalized = raw_content.strip()
        if normalized.startswith("```"):
            lines = normalized.splitlines()
            if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
                normalized = "\n".join(lines[1:-1]).strip()
                if normalized.lower().startswith("json"):
                    normalized = normalized[4:].strip()

        parsed = json.loads(normalized)
        draft = DraftResponse.model_validate(parsed)
        if not draft.cited_policy_ids:
            raise ValueError("Draft response must include at least one cited policy id.")
        return draft

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You draft customer support email replies. "
            "Use only provided policy snippets. "
            "Return valid JSON only with keys: "
            "ticket_id, subject, reply, cited_policy_ids, escalation_note."
        )

    @staticmethod
    def _build_user_prompt(
        ticket: Ticket,
        triage: TriageResult,
        retrieved_policies: list[Policy],
        rules: DraftingRules,
    ) -> str:
        policy_snippets = []
        for policy in retrieved_policies:
            snippet = (
                f"- {policy.policy_id} | {policy.title}\n"
                f"  content: {policy.content}\n"
                f"  tags: {', '.join(policy.tags)}"
            )
            policy_snippets.append(snippet)

        tone_rules = "\n".join(f"- {item}" for item in rules.tone_requirements)
        prohibited = "\n".join(f"- {item}" for item in rules.prohibited_claims)
        output_keys = ", ".join(rules.required_output_keys)
        return (
            "Draft a customer-facing support reply using only the retrieved policy snippets.\n"
            "Do not claim completion if escalation is required.\n\n"
            "Ticket:\n"
            f"- ticket_id: {ticket.ticket_id}\n"
            f"- customer_name: {ticket.customer_name}\n"
            f"- subject: {ticket.subject}\n"
            f"- message: {ticket.message}\n"
            f"- language: {ticket.language}\n\n"
            "Triage result:\n"
            f"- category: {triage.category}\n"
            f"- priority: {triage.priority}\n"
            f"- should_escalate: {triage.should_escalate}\n"
            f"- reason: {triage.reason}\n"
            f"- missing_information: {', '.join(triage.missing_information)}\n\n"
            "Retrieved policy snippets:\n"
            f"{chr(10).join(policy_snippets)}\n\n"
            "Tone requirements:\n"
            f"{tone_rules}\n\n"
            "Prohibited claims:\n"
            f"{prohibited}\n\n"
            f"Required output keys: {output_keys}\n"
            "Output JSON only with shape:\n"
            "{\n"
            '  "ticket_id": "string",\n'
            '  "subject": "string",\n'
            '  "reply": "string",\n'
            '  "cited_policy_ids": ["string"],\n'
            '  "escalation_note": "string | null"\n'
            "}"
        )


class DraftingStageRunner:
    def __init__(
        self,
        service: OpenRouterDraftingService,
        artifact_store: JsonArtifactStore,
    ) -> None:
        self._service = service
        self._artifact_store = artifact_store

    def run(
        self,
        inputs: list[DraftingInput],
        rules: DraftingRules,
        draft_artifact_path: Path,
        llm_calls_artifact_path: Path,
        input_artifacts: list[str],
    ) -> DraftingStageResult:
        records: list[DraftResponse] = []
        for item in inputs:
            draft, prompt_hash = self._service.draft_response(
                ticket=item.ticket,
                triage=item.triage,
                retrieved_policies=item.retrieved_policies,
                rules=rules,
            )
            records.append(draft)
            self._artifact_store.append_llm_call(
                llm_calls_artifact_path,
                LLMCallRecord(
                    stage="drafting",
                    ticket_id=item.ticket.ticket_id,
                    timestamp=datetime.now(timezone.utc),
                    provider="openrouter",
                    model=self._service.model,
                    prompt_hash=prompt_hash,
                    input_artifacts=input_artifacts,
                    output_artifact=str(draft_artifact_path),
                ),
            )

        self._artifact_store.write_drafts(draft_artifact_path, records)
        return DraftingStageResult(records=records)
