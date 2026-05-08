from __future__ import annotations

from pathlib import Path

from ai.runtime import AIConfig


class LocalHeuristicProvider:
    """Safe local fallback runtime metadata provider."""

    def __init__(self, *, config: AIConfig) -> None:
        self.config = config

    def generate_structured_text(self, *, prompt: str, model_id: str, timeout_seconds: float) -> str:
        _ = prompt, model_id, timeout_seconds
        raise RuntimeError("local heuristic provider does not perform cloud text generation")

    def analyze_image_with_context(
        self,
        *,
        image_path: str | Path,
        prompt: str,
        model_id: str,
        timeout_seconds: float,
    ) -> str:
        _ = image_path, prompt, model_id, timeout_seconds
        raise RuntimeError("local heuristic provider does not perform cloud image generation")

    def health_check(self) -> dict[str, object]:
        runtime = self.describe_runtime()
        return {
            "status": "ok",
            "provider": runtime["provider"],
            "runtime_mode": runtime["runtime_mode"],
        }

    def describe_runtime(self) -> dict[str, object]:
        auth_mode = self.config.auth_mode
        auth_source = "disabled" if auth_mode == "disabled" else "none"
        return {
            "provider": "local_heuristic",
            "runtime_mode": "local_heuristic",
            "auth_mode": auth_mode,
            "auth_source": auth_source,
            "project_id": self.config.project_id,
            "location": self.config.location,
            "cloud_enabled": False,
            "circuit_breaker_open": False,
        }
