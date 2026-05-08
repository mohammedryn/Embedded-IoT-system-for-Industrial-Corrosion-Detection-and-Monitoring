from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class AIProvider(Protocol):
    def generate_structured_text(self, *, prompt: str, model_id: str, timeout_seconds: float) -> str:
        """Return structured text from a provider call."""

    def analyze_image_with_context(
        self,
        *,
        image_path: str | Path,
        prompt: str,
        model_id: str,
        timeout_seconds: float,
    ) -> str:
        """Return structured image analysis from a provider call."""

    def health_check(self) -> dict[str, Any]:
        """Return provider health metadata."""

    def describe_runtime(self) -> dict[str, Any]:
        """Return runtime metadata for logs and UI."""
