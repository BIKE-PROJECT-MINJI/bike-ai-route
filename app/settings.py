from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerSettings:
    openai_api_key: str | None
    openai_model: str
    gemini_api_key: str | None
    gemini_model: str

    @classmethod
    def from_env(cls) -> "WorkerSettings":
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
            gemini_model=os.getenv("GEMINI_MODEL") or os.getenv("GOOGLE_MODEL", "gemini-2.5-flash"),
        )

    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key or self.openai_api_key)

    @property
    def llm_provider(self) -> str:
        if self.gemini_api_key:
            return "gemini"
        if self.openai_api_key:
            return "openai"
        return "none"
