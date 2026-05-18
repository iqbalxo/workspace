from __future__ import annotations

from dataclasses import dataclass

from support_pipeline.types import PipelineStage


class StageTransitionError(ValueError):
    """Raised when pipeline stages are traversed out of order."""


@dataclass
class OrderedStageTracker:
    _current_stage: PipelineStage = PipelineStage.INIT

    _ordered_stages = (
        PipelineStage.INIT,
        PipelineStage.INPUTS_LOADED,
        PipelineStage.TICKETS_PARSED,
        PipelineStage.KB_INDEXED,
        PipelineStage.TICKET_TRIAGED,
        PipelineStage.EVIDENCE_RETRIEVED,
        PipelineStage.RESPONSE_DRAFTED,
        PipelineStage.RESPONSE_CHECKED,
        PipelineStage.RESPONSE_FINALISED,
    )

    @property
    def current_stage(self) -> PipelineStage:
        return self._current_stage

    def transition_to(self, next_stage: PipelineStage) -> None:
        current_index = self._ordered_stages.index(self._current_stage)
        if current_index == len(self._ordered_stages) - 1:
            raise StageTransitionError(
                f"Pipeline is already in final stage: {self._current_stage.value}"
            )

        expected_next_stage = self._ordered_stages[current_index + 1]
        if next_stage != expected_next_stage:
            raise StageTransitionError(
                "Invalid stage transition: "
                f"{self._current_stage.value} -> {next_stage.value}. "
                f"Expected: {expected_next_stage.value}"
            )

        self._current_stage = next_stage
