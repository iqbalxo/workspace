from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                records.append(json.loads(text))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path} line {line_no}: {exc}") from exc
    return records


def _validate_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate(repo_root: Path) -> tuple[bool, list[str]]:
    issues: list[str] = []

    required_files = [
        "tickets.json",
        "policy_kb.json",
        "triage.json",
        "retrieval_results.json",
        "draft_responses.json",
        "response_checks.json",
        "final_responses.json",
        "llm_calls.jsonl",
        "review_results.json",
    ]
    missing = [name for name in required_files if not (repo_root / name).exists()]
    if missing:
        issues.append(f"missing_artifacts:{','.join(missing)}")
        return False, issues

    tickets = _load_json(repo_root / "tickets.json")
    policy_kb = _load_json(repo_root / "policy_kb.json")
    triage = _load_json(repo_root / "triage.json")
    retrieval = _load_json(repo_root / "retrieval_results.json")
    drafts = _load_json(repo_root / "draft_responses.json")
    checks = _load_json(repo_root / "response_checks.json")
    finals = _load_json(repo_root / "final_responses.json")
    reviews = _load_json(repo_root / "review_results.json")
    llm_calls = _load_jsonl(repo_root / "llm_calls.jsonl")

    ticket_ids = {item["ticket_id"] for item in tickets}
    policy_ids = {item["policy_id"] for item in policy_kb}

    if len(triage) != len(ticket_ids):
        issues.append("triage_count_mismatch")
    if len(retrieval) != len(ticket_ids):
        issues.append("retrieval_count_mismatch")
    if len(drafts) != len(ticket_ids):
        issues.append("draft_count_mismatch")
    if len(checks) != len(ticket_ids):
        issues.append("check_count_mismatch")
    if len(finals) != len(ticket_ids):
        issues.append("final_count_mismatch")
    if len(reviews) != len(ticket_ids):
        issues.append("review_count_mismatch")

    retrieval_by_ticket = {item["ticket_id"]: item for item in retrieval}
    checks_by_ticket = {item["ticket_id"]: item for item in checks}
    finals_by_ticket = {item["ticket_id"]: item for item in finals}
    reviews_by_ticket = {item["ticket_id"]: item for item in reviews}

    # Ensure retrieval likely used policy KB by validating all retrieved IDs exist in policy_kb.json.
    for item in retrieval:
        for policy_id in item.get("retrieved_policy_ids", []):
            if policy_id not in policy_ids:
                issues.append(f"retrieval_unknown_policy:{item['ticket_id']}:{policy_id}")

    # Draft citations must be subset of retrieved IDs.
    for draft in drafts:
        ticket_id = draft["ticket_id"]
        retrieved = set(retrieval_by_ticket.get(ticket_id, {}).get("retrieved_policy_ids", []))
        for cited in draft.get("cited_policy_ids", []):
            if cited not in retrieved:
                issues.append(f"draft_citation_outside_retrieval:{ticket_id}:{cited}")

    # Failed deterministic checks must map to needs_human_review.
    for ticket_id in ticket_ids:
        check = checks_by_ticket.get(ticket_id)
        final = finals_by_ticket.get(ticket_id)
        if not check or not final:
            continue
        if not check.get("passed", False) and final.get("final_status") != "needs_human_review":
            issues.append(f"check_failure_not_routed:{ticket_id}")

    # Reviewer disapproval should map to needs_human_review.
    for ticket_id in ticket_ids:
        review = reviews_by_ticket.get(ticket_id)
        final = finals_by_ticket.get(ticket_id)
        if not review or not final:
            continue
        if not review.get("approved", False) and final.get("final_status") != "needs_human_review":
            issues.append(f"review_failure_not_routed:{ticket_id}")

    # Validate LLM call records structure and per-ticket stage calls.
    required_llm_keys = {
        "stage",
        "ticket_id",
        "timestamp",
        "provider",
        "model",
        "prompt_hash",
        "input_artifacts",
        "output_artifact",
    }
    stage_counts: dict[str, dict[str, int]] = {"triage": {}, "drafting": {}, "review": {}}

    for record in llm_calls:
        missing_keys = sorted(required_llm_keys.difference(record))
        if missing_keys:
            issues.append(f"llm_record_missing_keys:{','.join(missing_keys)}")
            continue

        stage = record["stage"]
        ticket_id = record["ticket_id"]
        if ticket_id not in ticket_ids:
            issues.append(f"llm_unknown_ticket:{ticket_id}")
        if stage in stage_counts:
            stage_counts[stage][ticket_id] = stage_counts[stage].get(ticket_id, 0) + 1
        if not _validate_timestamp(record["timestamp"]):
            issues.append(f"llm_bad_timestamp:{ticket_id}:{stage}")

    for stage in ("triage", "drafting", "review"):
        for ticket_id in ticket_ids:
            if stage_counts[stage].get(ticket_id, 0) != 1:
                issues.append(f"llm_stage_count_error:{stage}:{ticket_id}")

    # Retrieval file must be generated before drafts artifact.
    retrieval_mtime = (repo_root / "retrieval_results.json").stat().st_mtime
    draft_mtime = (repo_root / "draft_responses.json").stat().st_mtime
    if retrieval_mtime > draft_mtime:
        issues.append("retrieval_not_before_drafting")

    # Ensure on-disk inputs are explicitly referenced in LLM calls.
    triage_inputs = [
        record
        for record in llm_calls
        if record.get("stage") == "triage" and "tickets.json" in " ".join(record.get("input_artifacts", []))
    ]
    if len(triage_inputs) != len(ticket_ids):
        issues.append("triage_calls_missing_tickets_input_artifact")

    return len(issues) == 0, sorted(set(issues))


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    passed, issues = validate(repo_root)
    if passed:
        print("VALIDATION PASSED")
        return 0

    print("VALIDATION FAILED")
    for issue in issues:
        print(f"- {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
