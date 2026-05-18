from __future__ import annotations

import re
from dataclasses import dataclass

from support_pipeline.types import Policy, RetrievalResult, Ticket, TriageResult


@dataclass(frozen=True)
class RetrievalStageResult:
    records: list[RetrievalResult]


class DeterministicRetrievalService:
    _token_pattern = re.compile(r"[a-z0-9]+")
    _stopwords = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "i",
        "if",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "please",
        "that",
        "the",
        "to",
        "was",
        "with",
        "you",
    }
    _category_keywords = {
        "withdrawal_issue": {"withdrawal", "pending", "process", "processing"},
        "payment_issue": {"payment", "deposit", "card", "charge", "refund", "duplicate"},
        "verification_issue": {"verification", "verify", "id", "kyc", "approve", "approval"},
        "account_closure": {"account", "closure", "close", "funds", "permanent"},
        "other": {"support", "issue"},
    }

    def retrieve_for_ticket(
        self,
        ticket: Ticket,
        triage: TriageResult,
        policies: list[Policy],
    ) -> RetrievalResult:
        ticket_tokens = self._normalize_tokens(f"{ticket.subject} {ticket.message}")
        scored_rows: list[tuple[Policy, int, int, int]] = []
        for policy in policies:
            policy_text_tokens = self._normalize_tokens(
                f"{policy.title} {policy.content} {' '.join(policy.tags)}"
            )
            overlap = len(ticket_tokens.intersection(policy_text_tokens))
            tag_overlap = len(ticket_tokens.intersection(set(map(str.lower, policy.tags))))
            category_boost = self._category_boost(triage.category, policy)
            score = overlap * 3 + tag_overlap * 5 + category_boost
            scored_rows.append((policy, score, overlap, tag_overlap))

        ranked_rows = sorted(
            scored_rows,
            key=lambda row: (-row[1], row[0].policy_id),
        )
        selected_rows = ranked_rows[:3]
        if len(selected_rows) < 2:
            selected_rows = ranked_rows[:2]

        if self._safety_policy_relevant(triage):
            selected_rows = self._ensure_safety_policy(selected_rows, ranked_rows)

        policy_ids = [row[0].policy_id for row in selected_rows]
        reasoning = self._build_reasoning(selected_rows)
        return RetrievalResult(
            ticket_id=ticket.ticket_id,
            retrieved_policy_ids=policy_ids,
            ranking_explanation=reasoning,
        )

    def _category_boost(self, category: str, policy: Policy) -> int:
        keywords = self._category_keywords.get(category, set())
        policy_tokens = self._normalize_tokens(
            f"{policy.title} {policy.content} {' '.join(policy.tags)}"
        )
        matches = len(keywords.intersection(policy_tokens))
        return matches * 7

    def _normalize_tokens(self, text: str) -> set[str]:
        tokens = {token.lower() for token in self._token_pattern.findall(text.lower())}
        return {token for token in tokens if token not in self._stopwords and len(token) > 1}

    def _safety_policy_relevant(self, triage: TriageResult) -> bool:
        return triage.should_escalate or triage.priority == "high"

    def _ensure_safety_policy(
        self,
        selected_rows: list[tuple[Policy, int, int, int]],
        ranked_rows: list[tuple[Policy, int, int, int]],
    ) -> list[tuple[Policy, int, int, int]]:
        if any(self._is_safety_policy(row[0]) for row in selected_rows):
            return selected_rows

        safety_row = next((row for row in ranked_rows if self._is_safety_policy(row[0])), None)
        if safety_row is None:
            return selected_rows

        if len(selected_rows) < 3:
            return selected_rows + [safety_row]

        retained = selected_rows[:-1]
        return retained + [safety_row]

    def _is_safety_policy(self, policy: Policy) -> bool:
        tags = {tag.lower() for tag in policy.tags}
        if {"safety", "tone", "escalation"}.intersection(tags):
            return True
        text = f"{policy.title} {policy.content}".lower()
        return any(keyword in text for keyword in ("safety", "tone", "escalate"))

    def _build_reasoning(self, selected_rows: list[tuple[Policy, int, int, int]]) -> str:
        parts: list[str] = []
        for policy, score, overlap, tag_overlap in selected_rows:
            parts.append(
                f"{policy.policy_id}:score={score}(token_overlap={overlap},tag_overlap={tag_overlap})"
            )
        return "; ".join(parts)
