from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class OpenRouterSettings:
    api_key: str
    model: str
    base_url: str

    @classmethod
    def from_env(cls) -> "OpenRouterSettings":
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required for triage stage.")

        model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()
        base_url = os.getenv(
            "OPENROUTER_BASE_URL",
            "https://openrouter.ai/api/v1",
        ).strip()
        return cls(api_key=api_key, model=model, base_url=base_url)
