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
    expert_summary: str
    mechanistic_interpretation: str
    corrosion_mode: str
    key_findings: list[str]
    recommended_actions: list[str]
    source_ids: list[str]
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
    surface_summary: str
    pit_suspected: bool
    pit_evidence: str
    suspected_damage_modes: list[str]
    key_findings: list[str]
    recommended_actions: list[str]
    source_ids: list[str]
    uncertainty_drivers: list[str]
    quality_flags: list[str]
    degraded_mode: bool
    stale: bool
    fallback_reason: str
    model_id: str
    schema_version: str


class FinalInterpretationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    cycle_id: str
    headline: str
    overall_condition: str
    executive_summary: str
    electrochemical_assessment: list[str]
    vision_assessment: list[str]
    cross_modal_assessment: list[str]
    limitations: list[str]
    recommendations: list[str]
    confidence_0_to_1: float = Field(ge=0.0, le=1.0)
    source_ids: list[str]
    degraded_mode: bool
    stale: bool
    fallback_reason: str
    model_id: str
    schema_version: str


class ModelClient(Protocol):
    def generate_structured_text(self, *, model_id: str, prompt: str, timeout_seconds: float) -> str:
        """Return a JSON string from a model call."""


@dataclass(frozen=True)
class AISettings:
    primary_model_id: str
    fallback_model_id: str
    response_mode: str
    max_attempts: int
    timeout_seconds: float
    backoff_seconds: float


@dataclass(frozen=True)
class CorrosionMemory:
    project_domain: dict[str, Any]
    interpretation_rules: list[dict[str, Any]]
    source_memory: list[dict[str, Any]]
    vision_rules: list[dict[str, Any]]
    orchestration_rules: list[dict[str, Any]]


def load_ai_settings(project_root: str | Path) -> AISettings:
    from ai.runtime import load_ai_config

    config = load_ai_config(project_root)

    return AISettings(
        primary_model_id=config.primary_model_id,
        fallback_model_id=config.fallback_model_id,
        response_mode="json",
        max_attempts=config.max_attempts,
        timeout_seconds=config.sensor_timeout_seconds,
        backoff_seconds=config.backoff_seconds,
    )


def load_corrosion_memory(project_root: str | Path) -> CorrosionMemory:
    root = Path(project_root)
    payload = yaml.safe_load((root / "config" / "corrosion_memory.yaml").read_text(encoding="utf-8")) or {}
    return CorrosionMemory(
        project_domain=dict(payload.get("project_domain", {})),
        interpretation_rules=list(payload.get("interpretation_rules", [])),
        source_memory=list(payload.get("source_memory", [])),
        vision_rules=list(payload.get("vision_rules", [])),
        orchestration_rules=list(payload.get("orchestration_rules", [])),
    )


class PromptTemplates:
    """Deterministic templates with stable key ordering for reproducible model inputs."""

    SENSOR_TEMPLATE = (
        "You are the Electrochemical Corrosion Specialist. "
        "Return STRICT JSON only with no markdown, no prose, and no extra keys.\n"
        "Schema: {{"
        "timestamp:string, cycle_id:string, rp_ohm:number, current_ma:number, status_band:string, "
        "electrochemical_severity_0_to_10:number[0..10], confidence_0_to_1:number[0..1], "
        "expert_summary:string, mechanistic_interpretation:string, corrosion_mode:string, "
        "key_findings:string[], recommended_actions:string[], source_ids:string[], uncertainty_drivers:string[], quality_flags:string[], "
        "degraded_mode:boolean, stale:boolean, fallback_reason:string, model_id:string, schema_version:string"
        "}}.\n"
        "Rules: keep numbers realistic, keep arrays non-empty with information-dense items, source_ids must be selected from the research memory, "
        "and set schema_version to c05-sensor-v1.\n"
        "Research memory:\n{memory_text}\n"
        "Input JSON:\n{input_json}\n"
    )

    VISION_TEMPLATE = (
        "You are the Vision Corrosion Specialist. "
        "Return STRICT JSON only with no markdown, no prose, and no extra keys.\n"
        "Schema: {{"
        "timestamp:string, cycle_id:string, visual_severity_0_to_10:number[0..10], confidence_0_to_1:number[0..1], "
        "rust_coverage_band:string, morphology_class:string, surface_summary:string, pit_suspected:boolean, pit_evidence:string, "
        "suspected_damage_modes:string[], key_findings:string[], recommended_actions:string[], source_ids:string[], uncertainty_drivers:string[], "
        "quality_flags:string[], degraded_mode:boolean, stale:boolean, fallback_reason:string, model_id:string, schema_version:string"
        "}}.\n"
        "Rules: keep arrays non-empty with information-dense items, source_ids must be selected from the research memory, "
        "and set schema_version to c05-vision-v1.\n"
        "Research memory:\n{memory_text}\n"
        "Input JSON:\n{input_json}\n"
    )

    ORCHESTRATOR_TEMPLATE = (
        "You are the Final Corrosion Interpretation Specialist. "
        "Fuse the electrochemical and vision specialist outputs into a detailed, technically careful corrosion report. "
        "Return STRICT JSON only with no markdown, no prose outside the JSON object, and no extra keys.\n"
        "Schema: {{"
        "timestamp:string, cycle_id:string, headline:string, overall_condition:string, executive_summary:string, "
        "electrochemical_assessment:string[], vision_assessment:string[], cross_modal_assessment:string[], "
        "limitations:string[], recommendations:string[], confidence_0_to_1:number[0..1], source_ids:string[], "
        "degraded_mode:boolean, stale:boolean, fallback_reason:string, model_id:string, schema_version:string"
        "}}.\n"
        "Rules: be detailed, cautious, and research-grounded; write like a concise corrosion lab note rather than a generic AI summary; "
        "do not invent quantitative corrosion rates from Rp unless the inputs justify it; source_ids must be selected from the research memory; "
        "arrays must be non-empty with information-dense items; set schema_version to c05-final-v1.\n"
        "Research memory:\n{memory_text}\n"
        "Input JSON:\n{input_json}\n"
    )

    @staticmethod
    def _memory_to_text(memory: CorrosionMemory, *, include_vision: bool, include_orchestration: bool) -> str:
        lines: list[str] = []
        if memory.project_domain:
            lines.append("PROJECT DOMAIN:")
            for key, value in memory.project_domain.items():
                lines.append(f"- {key}: {value}")
        if memory.interpretation_rules:
            lines.append("INTERPRETATION RULES:")
            for item in memory.interpretation_rules:
                lines.append(f"- {item.get('id')}: {item.get('rule')}")
        if include_vision and memory.vision_rules:
            lines.append("VISION RULES:")
            for item in memory.vision_rules:
                lines.append(f"- {item.get('id')}: {item.get('rule')}")
        if include_orchestration and memory.orchestration_rules:
            lines.append("ORCHESTRATION RULES:")
            for item in memory.orchestration_rules:
                lines.append(f"- {item.get('id')}: {item.get('rule')}")
        if memory.source_memory:
            lines.append("SOURCE MEMORY:")
            for src in memory.source_memory:
                lines.append(f"- {src.get('id')}: {src.get('title')} ({src.get('url')})")
                for point in src.get("key_points", []):
                    lines.append(f"  * {point}")
                for point in src.get("operational_use", []):
                    lines.append(f"  * operational_use: {point}")
        return "\n".join(lines)

    @staticmethod
    def build_sensor_prompt(sensor_input: dict[str, Any], memory: CorrosionMemory) -> str:
        return PromptTemplates.SENSOR_TEMPLATE.format(
            memory_text=PromptTemplates._memory_to_text(memory, include_vision=False, include_orchestration=False),
            input_json=json.dumps(sensor_input, sort_keys=True, separators=(",", ":")),
        )

    @staticmethod
    def build_vision_prompt(vision_input: dict[str, Any], memory: CorrosionMemory) -> str:
        return PromptTemplates.VISION_TEMPLATE.format(
            memory_text=PromptTemplates._memory_to_text(memory, include_vision=True, include_orchestration=False),
            input_json=json.dumps(vision_input, sort_keys=True, separators=(",", ":")),
        )

    @staticmethod
    def build_orchestrator_prompt(orchestrator_input: dict[str, Any], memory: CorrosionMemory) -> str:
        return PromptTemplates.ORCHESTRATOR_TEMPLATE.format(
            memory_text=PromptTemplates._memory_to_text(memory, include_vision=True, include_orchestration=True),
            input_json=json.dumps(orchestrator_input, sort_keys=True, separators=(",", ":")),
        )


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
        self.memory = load_corrosion_memory(self.project_root)
        self.sleep_fn = sleep_fn or time.sleep
        self.last_valid_sensor: dict[str, Any] | None = None
        self.last_valid_vision: dict[str, Any] | None = None
        self.last_valid_final: dict[str, Any] | None = None

    def run_sensor(self, *, cycle_id: str, sensor_input: dict[str, Any]) -> dict[str, Any]:
        prompt = PromptTemplates.build_sensor_prompt(sensor_input, self.memory)
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
                "expert_summary": "Electrochemical specialist response unavailable; using fallback summary.",
                "mechanistic_interpretation": "Fallback mode could not derive a research-grounded mechanism from the available sensor data alone.",
                "corrosion_mode": "unknown",
                "key_findings": ["no_valid_specialist_response"],
                "recommended_actions": ["Repeat the electrochemical run and verify wiring, cell geometry, and stabilization time."],
                "source_ids": ["metrohm_an_cor_003_2025", "cemconcomp_lpr_limitations_2006"],
            },
            last_valid=self.last_valid_sensor,
        )
        if not result.get("degraded_mode", False):
            self.last_valid_sensor = dict(result)
        return result

    def run_vision(self, *, cycle_id: str, vision_input: dict[str, Any]) -> dict[str, Any]:
        prompt = PromptTemplates.build_vision_prompt(vision_input, self.memory)
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
                "surface_summary": "Vision specialist response unavailable; using fallback summary.",
                "pit_suspected": False,
                "pit_evidence": "insufficient_ai_analysis",
                "suspected_damage_modes": ["unknown"],
                "key_findings": ["no_valid_specialist_response"],
                "recommended_actions": ["Capture sharper, well-lit images from multiple angles before relying on the visual interpretation."],
                "source_ids": ["orientjchem_neutral_chloride_2019", "corsci_metastable_pitting_304_2014"],
            },
            last_valid=self.last_valid_vision,
        )
        if not result.get("degraded_mode", False):
            self.last_valid_vision = dict(result)
        return result

    def run_final_interpretation(self, *, cycle_id: str, orchestrator_input: dict[str, Any]) -> dict[str, Any]:
        prompt = PromptTemplates.build_orchestrator_prompt(orchestrator_input, self.memory)
        result = self._run_with_policy(
            cycle_id=cycle_id,
            prompt=prompt,
            schema=FinalInterpretationResponse,
            schema_version="c05-final-v1",
            seed_payload={
                "headline": "Corrosion Assessment",
                "overall_condition": "unknown",
                "executive_summary": "Final corrosion interpretation unavailable; using fallback report.",
                "electrochemical_assessment": ["Electrochemical specialist output was unavailable or incomplete."],
                "vision_assessment": ["Vision specialist output was unavailable or incomplete."],
                "cross_modal_assessment": ["Cross-modal fusion could not be expanded into an AI narrative report."],
                "limitations": ["Fallback mode reduces interpretive detail and may understate nuanced corrosion behavior."],
                "recommendations": ["Repeat the run with stable readings and at least one high-quality image, then retry analysis."],
                "confidence_0_to_1": float(orchestrator_input.get("fused", {}).get("confidence_0_to_1", 0.3)),
                "source_ids": ["metrohm_an_cor_003_2025", "cemconcomp_lpr_limitations_2006", "orientjchem_neutral_chloride_2019"],
            },
            last_valid=self.last_valid_final,
        )
        if not result.get("degraded_mode", False):
            self.last_valid_final = dict(result)
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
                raw = self.client.generate_structured_text(
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
            except Exception as exc:  # pylint: disable=broad-except
                last_error = f"model_call_exception:{type(exc).__name__}:{exc}"

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
            if "quality_flags" in stale:
                stale["quality_flags"] = flags
            uncertainty = list(stale.get("uncertainty_drivers", []))
            if "stale_fallback_used" not in uncertainty:
                uncertainty.append("stale_fallback_used")
            if "uncertainty_drivers" in stale:
                stale["uncertainty_drivers"] = uncertainty
            stale["schema_version"] = schema_version
            return schema.model_validate(stale).model_dump()

        payload = {
            "timestamp": now,
            "cycle_id": cycle_id,
            "degraded_mode": True,
            "stale": True,
            "fallback_reason": fallback_reason,
            "model_id": model_id,
            "schema_version": schema_version,
            **seed_payload,
        }
        if "key_findings" in schema.model_fields:
            payload.setdefault("key_findings", ["no_valid_specialist_response"])
        if "uncertainty_drivers" in schema.model_fields:
            payload.setdefault("uncertainty_drivers", ["degraded_mode", "stale_fallback_used"])
        if "quality_flags" in schema.model_fields:
            payload.setdefault("quality_flags", ["stale_result"])
        return schema.model_validate(payload).model_dump()


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()
