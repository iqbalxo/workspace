from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, TypeAdapter

from support_pipeline.artifact_store import JsonArtifactStore
from support_pipeline.settings import OpenRouterSettings
from support_pipeline.types import LLMCallRecord, Ticket, TriageResult


class TriageRules(BaseModel):
    categories: list[str]
    escalation_rules: list[str]


@dataclass(frozen=True)
class TriageStageResult:
    records: list[TriageResult]


class OpenRouterTriageService:
    def __init__(self, settings: OpenRouterSettings, timeout_seconds: float = 60.0) -> None:
        self._settings = settings
        self._timeout_seconds = timeout_seconds

    def triage_ticket(self, ticket: Ticket, rules: TriageRules) -> tuple[TriageResult, str]:
        prompt = self._build_user_prompt(ticket=ticket, rules=rules)
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
        triage = self._parse_triage(content)
        triage.ticket_id = ticket.ticket_id
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return triage, prompt_hash

    @property
    def model(self) -> str:
        return self._settings.model

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
    def _parse_triage(raw_content: str) -> TriageResult:
        raw_content = raw_content.strip()
        if raw_content.startswith("```"):
            lines = raw_content.splitlines()
            if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
                raw_content = "\n".join(lines[1:-1]).strip()
                if raw_content.lower().startswith("json"):
                    raw_content = raw_content[4:].strip()

        parsed = json.loads(raw_content)
        return TriageResult.model_validate(parsed)

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You classify customer support tickets. "
            "Return valid JSON only with keys: "
            "ticket_id, category, priority, should_escalate, reason, missing_information."
        )

    @staticmethod
    def _build_user_prompt(ticket: Ticket, rules: TriageRules) -> str:
        categories = ", ".join(rules.categories)
        escalation_rules = "\n".join(f"- {rule}" for rule in rules.escalation_rules)
        return (
            "Classify this ticket using the allowed categories and rules.\n"
            f"Allowed categories: {categories}\n"
            "Priority values: high | medium | low\n"
            "Escalation rules:\n"
            f"{escalation_rules}\n\n"
            "Ticket:\n"
            f"- ticket_id: {ticket.ticket_id}\n"
            f"- subject: {ticket.subject}\n"
            f"- message: {ticket.message}\n"
            f"- language: {ticket.language}\n\n"
            "Return JSON with:\n"
            "{\n"
            '  "ticket_id": "string",\n'
            '  "category": "withdrawal_issue | payment_issue | verification_issue | account_closure | other",\n'
            '  "priority": "high | medium | low",\n'
            '  "should_escalate": true,\n'
            '  "reason": "string",\n'
            '  "missing_information": ["string"]\n'
            "}"
        )


class TriageRulesLoader:
    _adapter = TypeAdapter(TriageRules)

    @classmethod
    def from_file(cls, path: Path) -> TriageRules:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls._adapter.validate_python(data)


class TriageStageRunner:
    def __init__(
        self,
        service: OpenRouterTriageService,
        artifact_store: JsonArtifactStore,
    ) -> None:
        self._service = service
        self._artifact_store = artifact_store

    def run(
        self,
        tickets: list[Ticket],
        rules: TriageRules,
        triage_artifact_path: Path,
        llm_calls_artifact_path: Path,
        input_artifacts: list[str],
    ) -> TriageStageResult:
        results: list[TriageResult] = []
        for ticket in tickets:
            triage, prompt_hash = self._service.triage_ticket(ticket=ticket, rules=rules)
            results.append(triage)

            self._artifact_store.append_llm_call(
                llm_calls_artifact_path,
                LLMCallRecord(
                    stage="triage",
                    ticket_id=ticket.ticket_id,
                    timestamp=datetime.now(timezone.utc),
                    provider="openrouter",
                    model=self._service.model,
                    prompt_hash=prompt_hash,
                    input_artifacts=input_artifacts,
                    output_artifact=str(triage_artifact_path),
                ),
            )

        self._artifact_store.write_triage(triage_artifact_path, results)
        return TriageStageResult(records=results)
