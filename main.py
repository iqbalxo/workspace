from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from support_pipeline.artifact_store import JsonArtifactStore
from support_pipeline.pipeline import PhaseOneBootstrapRunner, PhaseTwoTriageRunner
from support_pipeline.settings import OpenRouterSettings
from support_pipeline.stage_tracker import OrderedStageTracker
from support_pipeline.triage import OpenRouterTriageService, TriageStageRunner


def run_pipeline_until_triage(repo_root: Path) -> None:
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

    tickets_path = repo_root / "tickets.json"
    policy_kb_path = repo_root / "policy_kb.json"
    triage_rules_path = repo_root / "config" / "triage_rules.json"
    triage_output_path = repo_root / "triage.json"
    llm_calls_output_path = repo_root / "llm_calls.jsonl"
    if llm_calls_output_path.exists():
        llm_calls_output_path.unlink()

    artifacts = phase_one.run(tickets_path=tickets_path, policy_kb_path=policy_kb_path)
    phase_two.run(
        tickets=artifacts.tickets,
        rules_path=triage_rules_path,
        triage_artifact_path=triage_output_path,
        llm_calls_artifact_path=llm_calls_output_path,
        input_artifacts=[
            str(tickets_path),
            str(triage_rules_path),
        ],
    )

    print(f"Current stage: {stage_tracker.current_stage.value}")
    print(f"Tickets loaded: {len(artifacts.tickets)}")
    print(f"Policies indexed: {len(artifacts.policy_index)}")
    print(f"Triage output: {triage_output_path.name}")
    print(f"LLM call log: {llm_calls_output_path.name}")


if __name__ == "__main__":
    run_pipeline_until_triage(repo_root=Path(__file__).resolve().parent)
