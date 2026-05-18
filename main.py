from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from support_pipeline.artifact_store import JsonArtifactStore
from support_pipeline.drafting import OpenRouterDraftingService, DraftingStageRunner
from support_pipeline.finalization import DeterministicFinalizationRunner
from support_pipeline.pipeline import (
    PhaseFiveResponseCheckRunner,
    PhaseSevenReviewerRunner,
    PhaseSixFinalizationRunner,
    PhaseFourDraftingRunner,
    PhaseOneBootstrapRunner,
    PhaseThreeRetrievalRunner,
    PhaseTwoTriageRunner,
)
from support_pipeline.retrieval import DeterministicRetrievalService
from support_pipeline.reviewer import OpenRouterReviewerService, OpenRouterReviewerStageRunner
from support_pipeline.response_checks import DeterministicResponseCheckRunner
from support_pipeline.settings import OpenRouterSettings
from support_pipeline.stage_tracker import OrderedStageTracker
from support_pipeline.triage import OpenRouterTriageService, TriageStageRunner


def run_pipeline_until_finalization(repo_root: Path) -> None:
    load_dotenv(repo_root / ".env")
    artifact_store = JsonArtifactStore()
    stage_tracker = OrderedStageTracker()
    phase_one = PhaseOneBootstrapRunner(
        artifact_store=artifact_store,
        stage_tracker=stage_tracker,
    )
    settings = OpenRouterSettings.from_env()
    triage_service = OpenRouterTriageService(settings=settings)
    triage_stage_runner = TriageStageRunner(
        service=triage_service,
        artifact_store=artifact_store,
    )
    phase_two = PhaseTwoTriageRunner(
        stage_tracker=stage_tracker,
        triage_runner=triage_stage_runner,
    )
    phase_three = PhaseThreeRetrievalRunner(
        stage_tracker=stage_tracker,
        artifact_store=artifact_store,
        retrieval_service=DeterministicRetrievalService(),
    )
    drafting_service = OpenRouterDraftingService(settings=settings)
    drafting_stage_runner = DraftingStageRunner(
        service=drafting_service,
        artifact_store=artifact_store,
    )
    phase_four = PhaseFourDraftingRunner(
        stage_tracker=stage_tracker,
        drafting_runner=drafting_stage_runner,
    )
    phase_five = PhaseFiveResponseCheckRunner(
        stage_tracker=stage_tracker,
        check_runner=DeterministicResponseCheckRunner(artifact_store=artifact_store),
    )
    reviewer_service = OpenRouterReviewerService(settings=settings)
    reviewer_stage_runner = OpenRouterReviewerStageRunner(
        service=reviewer_service,
        artifact_store=artifact_store,
    )
    phase_seven = PhaseSevenReviewerRunner(reviewer_runner=reviewer_stage_runner)
    phase_six = PhaseSixFinalizationRunner(
        stage_tracker=stage_tracker,
        finalization_runner=DeterministicFinalizationRunner(artifact_store=artifact_store),
    )

    tickets_path = repo_root / "tickets.json"
    policy_kb_path = repo_root / "policy_kb.json"
    triage_rules_path = repo_root / "config" / "triage_rules.json"
    triage_output_path = repo_root / "triage.json"
    retrieval_output_path = repo_root / "retrieval_results.json"
    drafting_rules_path = repo_root / "config" / "drafting_rules.json"
    drafts_output_path = repo_root / "draft_responses.json"
    response_check_rules_path = repo_root / "config" / "response_check_rules.json"
    response_checks_output_path = repo_root / "response_checks.json"
    reviewer_rules_path = repo_root / "config" / "reviewer_rules.json"
    review_results_output_path = repo_root / "review_results.json"
    finalization_rules_path = repo_root / "config" / "finalization_rules.json"
    final_responses_output_path = repo_root / "final_responses.json"
    llm_calls_output_path = repo_root / "llm_calls.jsonl"
    if llm_calls_output_path.exists():
        llm_calls_output_path.unlink()

    artifacts = phase_one.run(tickets_path=tickets_path, policy_kb_path=policy_kb_path)
    triage_records = phase_two.run(
        tickets=artifacts.tickets,
        rules_path=triage_rules_path,
        triage_artifact_path=triage_output_path,
        llm_calls_artifact_path=llm_calls_output_path,
        input_artifacts=[
            str(tickets_path),
            str(triage_rules_path),
        ],
    )
    retrieval_result = phase_three.run(
        tickets=artifacts.tickets,
        triage_records=triage_records,
        policies=artifacts.policies,
        retrieval_artifact_path=retrieval_output_path,
    )
    draft_records = phase_four.run(
        tickets=artifacts.tickets,
        triage_records=triage_records,
        retrieval_records=retrieval_result.records,
        policy_index=artifacts.policy_index,
        rules_path=drafting_rules_path,
        drafts_artifact_path=drafts_output_path,
        llm_calls_artifact_path=llm_calls_output_path,
        input_artifacts=[
            str(tickets_path),
            str(triage_output_path),
            str(retrieval_output_path),
            str(drafting_rules_path),
        ],
    )
    check_records = phase_five.run(
        tickets=artifacts.tickets,
        triage_records=triage_records,
        retrieval_records=retrieval_result.records,
        draft_records=draft_records,
        rules_path=response_check_rules_path,
        checks_artifact_path=response_checks_output_path,
    )
    review_records = phase_seven.run(
        tickets=artifacts.tickets,
        triage_records=triage_records,
        retrieval_records=retrieval_result.records,
        draft_records=draft_records,
        rules_path=reviewer_rules_path,
        review_artifact_path=review_results_output_path,
        llm_calls_artifact_path=llm_calls_output_path,
        input_artifacts=[
            str(tickets_path),
            str(triage_output_path),
            str(retrieval_output_path),
            str(drafts_output_path),
            str(reviewer_rules_path),
        ],
    )
    phase_six.run(
        triage_records=triage_records,
        retrieval_records=retrieval_result.records,
        draft_records=draft_records,
        check_records=check_records,
        review_records=review_records,
        rules_path=finalization_rules_path,
        final_artifact_path=final_responses_output_path,
    )

    print(f"Current stage: {stage_tracker.current_stage.value}")
    print(f"Tickets loaded: {len(artifacts.tickets)}")
    print(f"Policies indexed: {len(artifacts.policy_index)}")
    print(f"Triage output: {triage_output_path.name}")
    print(f"Retrieval output: {retrieval_output_path.name}")
    print(f"Draft output: {drafts_output_path.name}")
    print(f"Response checks output: {response_checks_output_path.name}")
    print(f"Review output: {review_results_output_path.name}")
    print(f"Final responses output: {final_responses_output_path.name}")
    print(f"LLM call log: {llm_calls_output_path.name}")


if __name__ == "__main__":
    run_pipeline_until_finalization(repo_root=Path(__file__).resolve().parent)
