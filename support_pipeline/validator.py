from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    issues: list[str]


class ArtifactValidator(Protocol):
    def validate(self, repo_root: Path) -> ValidationResult:
        ...
