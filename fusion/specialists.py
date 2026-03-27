from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class SensorSpecialistResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    cycle_id: str
    rp_ohm: float
    current_ma: float
    status_band: str
    electrochemical_severity_0_to_10: float = Field(ge=0.0, le=10.0)
    confidence_0_to_1: float = Field(ge=0.0, le=1.0)
    key_findings: list[str]
    uncertainty_drivers: list[str]
    quality_flags: list[str]
    degraded_mode: bool
    stale: bool
    fallback_reason: str
    model_id: str
    schema_version: str


class VisionSpecialistResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    cycle_id: str
    visual_severity_0_to_10: float = Field(ge=0.0, le=10.0)
    confidence_0_to_1: float = Field(ge=0.0, le=1.0)
    rust_coverage_band: str
    morphology_class: str
    key_findings: list[str]
    uncertainty_drivers: list[str]
    quality_flags: list[str]
    degraded_mode: bool
    stale: bool
    fallback_reason: str
    model_id: str
    schema_version: str


class ModelClient(Protocol):
    def generate(self, *, model_id: str, prompt: str, timeout_seconds: float) -> str:
        """Return a JSON string from a model call."""


@dataclass(frozen=True)
class AISettings:
    primary_model_id: str
    fallback_model_id: str
    response_mode: str
    max_attempts: int
    timeout_seconds: float
    backoff_seconds: float


def load_ai_settings(project_root: str | Path) -> AISettings:
    root = Path(project_root)
    settings = yaml.safe_load((root / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}
    retry = yaml.safe_load((root / "config" / "retry_policy.yaml").read_text(encoding="utf-8")) or {}

    ai_cfg = settings.get("ai", {})
    ai_retry = retry.get("retry", {}).get("ai_call", {})

    return AISettings(
        primary_model_id=str(ai_cfg.get("primary_model_id", "gemini-3-flash-preview")),
        fallback_model_id=str(ai_cfg.get("fallback_model_id", "gemini-3.1-pro-preview")),
        response_mode=str(ai_cfg.get("response_mode", "json")),
        max_attempts=int(ai_retry.get("max_attempts", 3)),
        timeout_seconds=float(ai_retry.get("timeout_seconds", 8)),
        backoff_seconds=float(ai_retry.get("backoff_seconds", 1)),
    )


class PromptTemplates:
    """Deterministic templates with stable key ordering for reproducible model inputs."""

    SENSOR_TEMPLATE = (
        "You are the Electrochemical Corrosion Specialist. "
        "Return STRICT JSON only with no markdown, no prose, no extra keys.\n"
        "Schema: {{"
        "timestamp:string, cycle_id:string, rp_ohm:number, current_ma:number, status_band:string, "
        "electrochemical_severity_0_to_10:number[0..10], confidence_0_to_1:number[0..1], "
        "key_findings:string[], uncertainty_drivers:string[], quality_flags:string[], "
        "degraded_mode:boolean, stale:boolean, fallback_reason:string, model_id:string, schema_version:string"
        "}}.\n"
        "Rules: keep numbers realistic, keep arrays non-empty, and set schema_version to c05-sensor-v1.\n"
        "Input JSON:\n{input_json}\n"
    )

    VISION_TEMPLATE = (
        "You are the Vision Corrosion Specialist. "
        "Return STRICT JSON only with no markdown, no prose, no extra keys.\n"
        "Schema: {{"
        "timestamp:string, cycle_id:string, visual_severity_0_to_10:number[0..10], confidence_0_to_1:number[0..1], "
        "rust_coverage_band:string, morphology_class:string, key_findings:string[], uncertainty_drivers:string[], "
        "quality_flags:string[], degraded_mode:boolean, stale:boolean, fallback_reason:string, model_id:string, schema_version:string"
        "}}.\n"
        "Rules: keep arrays non-empty and set schema_version to c05-vision-v1.\n"
        "Input JSON:\n{input_json}\n"
    )

    @staticmethod
    def build_sensor_prompt(sensor_input: dict[str, Any]) -> str:
        return PromptTemplates.SENSOR_TEMPLATE.format(input_json=json.dumps(sensor_input, sort_keys=True, separators=(",", ":")))

    @staticmethod
    def build_vision_prompt(vision_input: dict[str, Any]) -> str:
        return PromptTemplates.VISION_TEMPLATE.format(input_json=json.dumps(vision_input, sort_keys=True, separators=(",", ":")))


class SpecialistService:
    """C05 service for deterministic AI specialist calls with strict validation."""

    def __init__(
        self,
        project_root: str | Path,
        client: ModelClient,
        *,
        settings: AISettings | None = None,
        sleep_fn: Any | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.client = client
        self.settings = settings or load_ai_settings(self.project_root)
        self.sleep_fn = sleep_fn or time.sleep
        self.last_valid_sensor: dict[str, Any] | None = None
        self.last_valid_vision: dict[str, Any] | None = None

    def run_sensor(self, *, cycle_id: str, sensor_input: dict[str, Any]) -> dict[str, Any]:
        prompt = PromptTemplates.build_sensor_prompt(sensor_input)
        result = self._run_with_policy(
            cycle_id=cycle_id,
            prompt=prompt,
            schema=SensorSpecialistResponse,
            schema_version="c05-sensor-v1",
            seed_payload={
                "rp_ohm": float(sensor_input.get("rp_ohm", 0.0)),
                "current_ma": float(sensor_input.get("current_ma", 0.0)),
                "status_band": str(sensor_input.get("status_band", "unknown")),
                "electrochemical_severity_0_to_10": float(sensor_input.get("electrochemical_severity_0_to_10", 0.0)),
                "confidence_0_to_1": float(sensor_input.get("confidence_0_to_1", 0.2)),
            },
            last_valid=self.last_valid_sensor,
        )
        if not result.get("degraded_mode", False):
            self.last_valid_sensor = dict(result)
        return result

    def run_vision(self, *, cycle_id: str, vision_input: dict[str, Any]) -> dict[str, Any]:
        prompt = PromptTemplates.build_vision_prompt(vision_input)
        result = self._run_with_policy(
            cycle_id=cycle_id,
            prompt=prompt,
            schema=VisionSpecialistResponse,
            schema_version="c05-vision-v1",
            seed_payload={
                "visual_severity_0_to_10": float(vision_input.get("visual_severity_0_to_10", 0.0)),
                "confidence_0_to_1": float(vision_input.get("confidence_0_to_1", 0.2)),
                "rust_coverage_band": str(vision_input.get("rust_coverage_band", "unknown")),
                "morphology_class": str(vision_input.get("morphology_class", "unknown")),
            },
            last_valid=self.last_valid_vision,
        )
        if not result.get("degraded_mode", False):
            self.last_valid_vision = dict(result)
        return result

    def _run_with_policy(
        self,
        *,
        cycle_id: str,
        prompt: str,
        schema: type[BaseModel],
        schema_version: str,
        seed_payload: dict[str, Any],
        last_valid: dict[str, Any] | None,
    ) -> dict[str, Any]:
        attempts = max(1, self.settings.max_attempts)
        last_error = ""

        for attempt in range(1, attempts + 1):
            model_id = self.settings.primary_model_id if attempt < attempts else self.settings.fallback_model_id
            try:
                raw = self.client.generate(
                    model_id=model_id,
                    prompt=prompt,
                    timeout_seconds=self.settings.timeout_seconds,
                )
                parsed = self._strict_json_load(raw)
                parsed["cycle_id"] = cycle_id
                parsed["model_id"] = model_id
                parsed["schema_version"] = schema_version
                validated = schema.model_validate(parsed).model_dump()
                return validated
            except TimeoutError as exc:
                last_error = f"timeout:{exc}"
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = f"invalid_json_or_schema:{exc}"

            if attempt < attempts:
                self.sleep_fn(self.settings.backoff_seconds)

        return self._stale_fallback(
            cycle_id=cycle_id,
            seed_payload=seed_payload,
            schema_version=schema_version,
            fallback_reason=last_error or "unknown_error",
            model_id=self.settings.fallback_model_id,
            schema=schema,
            last_valid=last_valid,
        )

    @staticmethod
    def _strict_json_load(raw: str) -> dict[str, Any]:
        txt = raw.strip()
        if not txt.startswith("{") or not txt.endswith("}"):
            raise ValueError("response is not a JSON object")
        parsed = json.loads(txt)
        if not isinstance(parsed, dict):
            raise ValueError("response root is not an object")
        return parsed

    @staticmethod
    def _stale_fallback(
        *,
        cycle_id: str,
        seed_payload: dict[str, Any],
        schema_version: str,
        fallback_reason: str,
        model_id: str,
        schema: type[BaseModel],
        last_valid: dict[str, Any] | None,
    ) -> dict[str, Any]:
        now = _ts()
        if last_valid is not None:
            stale = dict(last_valid)
            stale["timestamp"] = now
            stale["cycle_id"] = cycle_id
            stale["degraded_mode"] = True
            stale["stale"] = True
            stale["fallback_reason"] = fallback_reason
            stale["model_id"] = model_id
            flags = list(stale.get("quality_flags", []))
            if "stale_result" not in flags:
                flags.append("stale_result")
            stale["quality_flags"] = flags
            uncertainty = list(stale.get("uncertainty_drivers", []))
            if "stale_fallback_used" not in uncertainty:
                uncertainty.append("stale_fallback_used")
            stale["uncertainty_drivers"] = uncertainty
            stale["schema_version"] = schema_version
            return schema.model_validate(stale).model_dump()

        payload = {
            "timestamp": now,
            "cycle_id": cycle_id,
            "key_findings": ["no_valid_specialist_response"],
            "uncertainty_drivers": ["degraded_mode", "stale_fallback_used"],
            "quality_flags": ["stale_result"],
            "degraded_mode": True,
            "stale": True,
            "fallback_reason": fallback_reason,
            "model_id": model_id,
            "schema_version": schema_version,
            **seed_payload,
        }
        return schema.model_validate(payload).model_dump()


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()
