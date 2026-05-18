from __future__ import annotations

from pathlib import Path

from support_pipeline.artifact_store import JsonArtifactStore
from support_pipeline.pipeline import PhaseOneBootstrapRunner
from support_pipeline.stage_tracker import OrderedStageTracker


def run_phase_one(repo_root: Path) -> None:
    artifact_store = JsonArtifactStore()
    stage_tracker = OrderedStageTracker()
    runner = PhaseOneBootstrapRunner(
        artifact_store=artifact_store,
        stage_tracker=stage_tracker,
    )

    tickets_path = repo_root / "tickets.json"
    policy_kb_path = repo_root / "policy_kb.json"

    artifacts = runner.run(tickets_path=tickets_path, policy_kb_path=policy_kb_path)
    print(f"Current stage: {stage_tracker.current_stage.value}")
    print(f"Tickets loaded: {len(artifacts.tickets)}")
    print(f"Policies indexed: {len(artifacts.policy_index)}")


if __name__ == "__main__":
    run_phase_one(repo_root=Path(__file__).resolve().parent)
