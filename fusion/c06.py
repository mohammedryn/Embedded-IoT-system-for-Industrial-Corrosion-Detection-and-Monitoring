from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from edge.src.logging_setup import configure_logging
from fusion.specialists import SensorSpecialistResponse, VisionSpecialistResponse


class RulConfidenceIntervalDays(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low: float = Field(ge=0.0)
    high: float = Field(ge=0.0)


class AppliedWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor: float = Field(ge=0.0, le=1.0)
    vision: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_sum(self) -> "AppliedWeights":
        if abs((self.sensor + self.vision) - 1.0) > 1e-9:
            raise ValueError("applied weights must sum to 1.0")
        return self


class FusedAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    cycle_id: str
    sensor_severity_0_to_10: float = Field(ge=0.0, le=10.0)
    vision_severity_0_to_10: float = Field(ge=0.0, le=10.0)
    severity_delta: float = Field(ge=0.0)
    conflict_detected: bool
    applied_weights: AppliedWeights
    fused_severity_0_to_10: float = Field(ge=0.0, le=10.0)
    rul_days: float = Field(ge=0.0)
    rul_confidence_interval_days: RulConfidenceIntervalDays
    confidence_0_to_1: float = Field(ge=0.0, le=1.0)
    rationale: str
    uncertainty_drivers: list[str]
    model_inputs_summary: dict[str, Any]
    ml_advisory_used: bool
    ml_override_reason: str | None
    degraded_mode: bool
    stale: bool
    schema_version: str


@dataclass(frozen=True)
class FusionSettings:
    sensor_weight: float
    vision_weight: float
    conflict_delta_threshold: float


def load_fusion_settings(project_root: str | Path) -> FusionSettings:
    root = Path(project_root)
    settings = yaml.safe_load((root / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}
    fusion_cfg = settings.get("fusion", {})
    sensor_weight = float(fusion_cfg.get("sensor_weight", 0.6))
    vision_weight = float(fusion_cfg.get("vision_weight", 0.4))

    return FusionSettings(
        sensor_weight=sensor_weight,
        vision_weight=vision_weight,
        conflict_delta_threshold=float(fusion_cfg.get("conflict_delta_threshold", 3.0)),
    )


class XgboostAdvisory(Protocol):
    def predict_rul_days(self, *, features: dict[str, Any]) -> float:
        """Return advisory RUL in days."""


class FusionService:
    """C06 fusion layer combining C05 specialist outputs into one strict payload."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        ml_advisory: XgboostAdvisory | None = None,
        settings: FusionSettings | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.settings = settings or load_fusion_settings(self.project_root)
        self.ml_advisory = ml_advisory
        self.last_valid_fused: dict[str, Any] | None = None

        configure_logging(self.project_root / "data" / "logs" / "fusion.log")
        self.logger = logging.getLogger("corrosion.fusion")
        self._validate_weights()

    def fuse(self, *, cycle_id: str, sensor_payload: dict[str, Any], vision_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            sensor = SensorSpecialistResponse.model_validate(sensor_payload).model_dump()
            vision = VisionSpecialistResponse.model_validate(vision_payload).model_dump()
        except ValidationError as exc:
            return self._degraded_fallback(
                cycle_id=cycle_id,
                sensor_payload=sensor_payload,
                vision_payload=vision_payload,
                fallback_reason=f"invalid_upstream_schema:{exc.errors()[0]['type']}",
            )

        try:
            return self._fuse_validated(cycle_id=cycle_id, sensor=sensor, vision=vision)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.exception(
                "fusion failed",
                extra={
                    "event": "fusion_error",
                    "component": "fusion",
                    "cycle_id": cycle_id,
                    "error": str(exc),
                },
            )
            return self._degraded_fallback(
                cycle_id=cycle_id,
                sensor_payload=sensor,
                vision_payload=vision,
                fallback_reason=f"fusion_exception:{type(exc).__name__}",
            )

    def _fuse_validated(self, *, cycle_id: str, sensor: dict[str, Any], vision: dict[str, Any]) -> dict[str, Any]:
        sensor_sev = float(sensor["electrochemical_severity_0_to_10"])
        vision_sev = float(vision["visual_severity_0_to_10"])
        sensor_conf = float(sensor["confidence_0_to_1"])
        vision_conf = float(vision["confidence_0_to_1"])

        delta = abs(sensor_sev - vision_sev)
        conflict = delta > self.settings.conflict_delta_threshold
        fused_severity = self._clamp(
            (self.settings.sensor_weight * sensor_sev) + (self.settings.vision_weight * vision_sev),
            0.0,
            10.0,
        )

        degraded = bool(sensor.get("degraded_mode", False) or vision.get("degraded_mode", False))
        stale = bool(sensor.get("stale", False) or vision.get("stale", False))

        confidence = (self.settings.sensor_weight * sensor_conf) + (self.settings.vision_weight * vision_conf)
        if conflict:
            confidence *= 0.85
        if degraded or stale:
            confidence *= 0.75
        confidence = self._clamp(confidence, 0.0, 1.0)

        uncertainty_drivers: list[str] = []
        if conflict:
            uncertainty_drivers.append("sensor_vision_conflict")
        if degraded:
            uncertainty_drivers.append("upstream_degraded_mode")
        if stale:
            uncertainty_drivers.append("upstream_stale")

        rul_days, ml_used, ml_override_reason = self._resolve_rul(
            fused_severity=fused_severity,
            conflict=conflict,
            sensor=sensor,
            vision=vision,
            uncertainty_drivers=uncertainty_drivers,
        )

        interval = self._build_rul_interval(
            rul_days=rul_days,
            confidence=confidence,
            conflict=conflict,
            degraded=degraded,
            stale=stale,
        )

        rationale = self._build_rationale(
            conflict=conflict,
            fused_severity=fused_severity,
            sensor_weight=self.settings.sensor_weight,
            vision_weight=self.settings.vision_weight,
            ml_used=ml_used,
            ml_override_reason=ml_override_reason,
        )

        payload = FusedAssessment(
            timestamp=_ts(),
            cycle_id=cycle_id,
            sensor_severity_0_to_10=round(sensor_sev, 4),
            vision_severity_0_to_10=round(vision_sev, 4),
            severity_delta=round(delta, 4),
            conflict_detected=conflict,
            applied_weights=AppliedWeights(sensor=self.settings.sensor_weight, vision=self.settings.vision_weight),
            fused_severity_0_to_10=round(fused_severity, 4),
            rul_days=round(rul_days, 2),
            rul_confidence_interval_days=interval,
            confidence_0_to_1=round(confidence, 4),
            rationale=rationale,
            uncertainty_drivers=sorted(set(uncertainty_drivers)),
            model_inputs_summary={
                "sensor_status_band": sensor.get("status_band", "unknown"),
                "vision_rust_coverage_band": vision.get("rust_coverage_band", "unknown"),
                "sensor_model_id": sensor.get("model_id", "unknown"),
                "vision_model_id": vision.get("model_id", "unknown"),
            },
            ml_advisory_used=ml_used,
            ml_override_reason=ml_override_reason,
            degraded_mode=degraded,
            stale=stale,
            schema_version="c06-fusion-v1",
        ).model_dump()

        if not payload["degraded_mode"] and not payload["stale"]:
            self.last_valid_fused = dict(payload)

        self.logger.info(
            "fusion completed",
            extra={
                "event": "fusion_result",
                "component": "fusion",
                "cycle_id": cycle_id,
                "conflict_detected": payload["conflict_detected"],
                "fused_severity_0_to_10": payload["fused_severity_0_to_10"],
                "rul_days": payload["rul_days"],
                "ml_advisory_used": payload["ml_advisory_used"],
                "ml_override_reason": payload["ml_override_reason"] or "",
            },
        )

        return payload

    def _resolve_rul(
        self,
        *,
        fused_severity: float,
        conflict: bool,
        sensor: dict[str, Any],
        vision: dict[str, Any],
        uncertainty_drivers: list[str],
    ) -> tuple[float, bool, str | None]:
        heuristic = self._heuristic_rul_days(fused_severity)
        if self.ml_advisory is None:
            uncertainty_drivers.append("ml_unavailable")
            return heuristic, False, "ml_unavailable_fallback_heuristic"

        features = {
            "sensor_severity_0_to_10": fused_severity,
            "sensor_confidence_0_to_1": sensor.get("confidence_0_to_1", 0.0),
            "vision_confidence_0_to_1": vision.get("confidence_0_to_1", 0.0),
            "conflict_detected": float(conflict),
        }

        try:
            advisory_rul = float(self.ml_advisory.predict_rul_days(features=features))
            if math.isnan(advisory_rul) or math.isinf(advisory_rul):
                raise ValueError("ml advisory invalid")
        except Exception as exc:  # pylint: disable=broad-except
            uncertainty_drivers.append("ml_unavailable")
            return heuristic, False, f"ml_unavailable_fallback_heuristic:{type(exc).__name__}"

        # Override obviously implausible advisory values to keep demo behavior stable.
        if advisory_rul <= 0.0 or advisory_rul > 3650.0 or abs(advisory_rul - heuristic) > 365.0:
            uncertainty_drivers.append("ml_override_applied")
            return heuristic, True, "ml_advisory_overridden_implausible_value"

        return advisory_rul, True, None

    @staticmethod
    def _heuristic_rul_days(fused_severity: float) -> float:
        sev = max(0.0, min(10.0, fused_severity))
        return round(365.0 - (sev * 33.5), 2)

    @staticmethod
    def _build_rul_interval(
        *,
        rul_days: float,
        confidence: float,
        conflict: bool,
        degraded: bool,
        stale: bool,
    ) -> RulConfidenceIntervalDays:
        spread = (1.0 - confidence) * 40.0
        if conflict:
            spread += 8.0
        if degraded or stale:
            spread += 10.0
        spread = max(5.0, spread)
        return RulConfidenceIntervalDays(
            low=round(max(0.0, rul_days - spread), 2),
            high=round(rul_days + spread, 2),
        )

    @staticmethod
    def _build_rationale(
        *,
        conflict: bool,
        fused_severity: float,
        sensor_weight: float,
        vision_weight: float,
        ml_used: bool,
        ml_override_reason: str | None,
    ) -> str:
        parts = [
            f"weighted fusion severity={fused_severity:.2f} using sensor={sensor_weight:.2f} and vision={vision_weight:.2f}",
            "conflict detected" if conflict else "no conflict detected",
        ]
        if not ml_used:
            parts.append("ml advisory unavailable; deterministic fallback heuristic applied")
        elif ml_override_reason:
            parts.append(f"ml advisory overridden: {ml_override_reason}")
        else:
            parts.append("ml advisory accepted")
        return "; ".join(parts)

    def _degraded_fallback(
        self,
        *,
        cycle_id: str,
        sensor_payload: dict[str, Any],
        vision_payload: dict[str, Any],
        fallback_reason: str,
    ) -> dict[str, Any]:
        if self.last_valid_fused is not None:
            stale = dict(self.last_valid_fused)
            stale["timestamp"] = _ts()
            stale["cycle_id"] = cycle_id
            stale["degraded_mode"] = True
            stale["stale"] = True
            stale["ml_override_reason"] = fallback_reason
            uncertainty = list(stale.get("uncertainty_drivers", []))
            uncertainty.append("stale_fallback_used")
            stale["uncertainty_drivers"] = sorted(set(uncertainty))
            return FusedAssessment.model_validate(stale).model_dump()

        sensor_sev = self._safe_float(sensor_payload.get("electrochemical_severity_0_to_10", 0.0))
        vision_sev = self._safe_float(vision_payload.get("visual_severity_0_to_10", 0.0))
        fused = self._clamp(
            (self.settings.sensor_weight * sensor_sev) + (self.settings.vision_weight * vision_sev),
            0.0,
            10.0,
        )
        rul = self._heuristic_rul_days(fused)
        payload = FusedAssessment(
            timestamp=_ts(),
            cycle_id=cycle_id,
            sensor_severity_0_to_10=round(sensor_sev, 4),
            vision_severity_0_to_10=round(vision_sev, 4),
            severity_delta=round(abs(sensor_sev - vision_sev), 4),
            conflict_detected=abs(sensor_sev - vision_sev) > self.settings.conflict_delta_threshold,
            applied_weights=AppliedWeights(sensor=self.settings.sensor_weight, vision=self.settings.vision_weight),
            fused_severity_0_to_10=round(fused, 4),
            rul_days=round(rul, 2),
            rul_confidence_interval_days=self._build_rul_interval(
                rul_days=rul,
                confidence=0.3,
                conflict=abs(sensor_sev - vision_sev) > self.settings.conflict_delta_threshold,
                degraded=True,
                stale=True,
            ),
            confidence_0_to_1=0.3,
            rationale="degraded fallback produced from available payloads",
            uncertainty_drivers=["degraded_mode", "stale_fallback_used", fallback_reason],
            model_inputs_summary={
                "sensor_status_band": str(sensor_payload.get("status_band", "unknown")),
                "vision_rust_coverage_band": str(vision_payload.get("rust_coverage_band", "unknown")),
                "sensor_model_id": str(sensor_payload.get("model_id", "unknown")),
                "vision_model_id": str(vision_payload.get("model_id", "unknown")),
            },
            ml_advisory_used=False,
            ml_override_reason=fallback_reason,
            degraded_mode=True,
            stale=True,
            schema_version="c06-fusion-v1",
        ).model_dump()

        self.logger.warning(
            "fusion degraded fallback",
            extra={
                "event": "fusion_degraded",
                "component": "fusion",
                "cycle_id": cycle_id,
                "fallback_reason": fallback_reason,
            },
        )
        return payload

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    def _validate_weights(self) -> None:
        AppliedWeights(sensor=self.settings.sensor_weight, vision=self.settings.vision_weight)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()