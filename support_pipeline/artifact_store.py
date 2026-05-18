from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, TypeAdapter

from support_pipeline.types import (
    DraftResponse,
    LLMCallRecord,
    Policy,
    ResponseCheck,
    RetrievalResult,
    ReviewResult,
    Ticket,
    TriageResult,
)


class JsonArtifactStore:
    """Deterministic artifact IO for reproducible offline pipeline runs."""

    _tickets_adapter = TypeAdapter(list[Ticket])
    _policies_adapter = TypeAdapter(list[Policy])

    def read_tickets(self, path: Path) -> list[Ticket]:
        raw = self._read_json(path)
        return self._tickets_adapter.validate_python(raw)

    def read_policies(self, path: Path) -> list[Policy]:
        raw = self._read_json(path)
        return self._policies_adapter.validate_python(raw)

    def write_triage(self, path: Path, records: Sequence[TriageResult]) -> None:
        self._write_json(path, records)

    def write_retrieval(self, path: Path, records: Sequence[RetrievalResult]) -> None:
        self._write_json(path, records)

    def write_drafts(self, path: Path, records: Sequence[DraftResponse]) -> None:
        self._write_json(path, records)

    def write_checks(self, path: Path, records: Sequence[ResponseCheck]) -> None:
        self._write_json(path, records)

    def write_review_results(self, path: Path, records: Sequence[ReviewResult]) -> None:
        self._write_json(path, records)

    def write_final(self, path: Path, records: Sequence[object]) -> None:
        self._write_json(path, records)

    def append_llm_call(self, path: Path, record: LLMCallRecord) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            payload = json.dumps(
                self._serialize_one(record),
                sort_keys=True,
                ensure_ascii=True,
                separators=(",", ":"),
            )
            handle.write(payload + "\n")

    def _read_json(self, path: Path) -> Any:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write_json(self, path: Path, records: Sequence[Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serializable = [self._serialize_one(record) for record in records]
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                serializable,
                handle,
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
            handle.write("\n")

    def _serialize_one(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return value
