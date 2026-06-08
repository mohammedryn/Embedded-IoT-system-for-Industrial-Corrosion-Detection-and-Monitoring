from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AIConfig:
    provider: str
    auth_mode: str
    project_id: str
    location: str
    primary_model_id: str
    fallback_model_id: str
    enable_cloud_vision: bool
    enable_cloud_orchestrator: bool
    browser_timeout_seconds: float
    sensor_timeout_seconds: float
    vision_timeout_seconds: float
    final_report_timeout_seconds: float
    ai_call_timeout_seconds: float
    max_attempts: int
    backoff_seconds: float
    circuit_breaker_failures: int
    circuit_breaker_cooldown_seconds: float


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in {path}")
    return payload


def load_ai_config(project_root: str | Path) -> AIConfig:
    root = Path(project_root)
    settings = _load_yaml(root / "config" / "settings.yaml")
    retry_policy = _load_yaml(root / "config" / "retry_policy.yaml")

    ai_cfg = settings.get("ai", {})
    retry_cfg = retry_policy.get("retry", {})
    ai_call = retry_cfg.get("ai_call", {})
    breaker_cfg = retry_cfg.get("ai_circuit_breaker", {})

    return AIConfig(
        provider=str(ai_cfg.get("provider", "vertex")),
        auth_mode=str(ai_cfg.get("auth_mode", "auto")),
        project_id=str(ai_cfg.get("project_id", "")),
        location=str(ai_cfg.get("location", "global")),
        primary_model_id=str(ai_cfg.get("primary_model_id", "gemini-2.5-flash")),
        fallback_model_id=str(ai_cfg.get("fallback_model_id", "gemini-2.5-pro")),
        enable_cloud_vision=bool(ai_cfg.get("enable_cloud_vision", True)),
        enable_cloud_orchestrator=bool(ai_cfg.get("enable_cloud_orchestrator", True)),
        browser_timeout_seconds=float(ai_cfg.get("browser_timeout_seconds", 25.0)),
        sensor_timeout_seconds=float(ai_cfg.get("sensor_timeout_seconds", 8.0)),
        vision_timeout_seconds=float(ai_cfg.get("vision_timeout_seconds", 10.0)),
        final_report_timeout_seconds=float(ai_cfg.get("final_report_timeout_seconds", 7.0)),
        ai_call_timeout_seconds=float(ai_call.get("timeout_seconds", 8.0)),
        max_attempts=int(ai_call.get("max_attempts", 2)),
        backoff_seconds=float(ai_call.get("backoff_seconds", 1.0)),
        circuit_breaker_failures=int(breaker_cfg.get("failures", 3)),
        circuit_breaker_cooldown_seconds=float(breaker_cfg.get("cooldown_seconds", 120.0)),
    )
