from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edge.src.logging_setup import configure_logging
from fusion.c06 import FusionService
from vision.pipeline import VisionPipeline

PHASES: tuple[str, ...] = (
    "baseline",
    "acceleration",
    "active",
    "severe",
    "fresh_swap",
)


@dataclass(frozen=True)
class PhaseProfile:
    rp_ohm: float
    current_ma: float
    status_band: str
    sensor_severity_0_to_10: float
    sensor_confidence_0_to_1: float


PHASE_PROFILES: dict[str, PhaseProfile] = {
    "baseline": PhaseProfile(62000.0, 0.11, "HEALTHY", 1.3, 0.94),
    "acceleration": PhaseProfile(42000.0, 0.23, "WARNING", 3.8, 0.88),
    "active": PhaseProfile(30000.0, 0.34, "WARNING", 5.7, 0.84),
    "severe": PhaseProfile(17000.0, 0.49, "CRITICAL", 8.4, 0.8),
    "fresh_swap": PhaseProfile(56000.0, 0.16, "HEALTHY", 2.2, 0.9),
}


class C07Orchestrator:
    """Phase-aware runtime orchestration with a single-screen dashboard model."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        vision_pipeline: VisionPipeline,
        fusion_service: FusionService,
        logger: logging.Logger | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.session_dir = self.project_root / "data" / "sessions" / "c07"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        if logger is None:
            configure_logging(self.project_root / "data" / "logs" / "c07.log")
            logger = logging.getLogger("corrosion.c07")
        self.logger = logger

        self.vision_pipeline = vision_pipeline
        self.fusion_service = fusion_service
        self.phase = PHASES[0]
        self.paused = False
        self._cycle_index = 0

        self._last_source_image: str | None = None
        self._last_sensor_payload: dict[str, Any] | None = None
        self._last_vision_payload: dict[str, Any] | None = None
        self._last_vision_result: dict[str, Any] | None = None
        self._last_dashboard_state: dict[str, Any] | None = None

        self._log_phase_transition(previous=None, current=self.phase)

    def transition_phase(self, next_phase: str) -> str:
        if next_phase not in PHASES:
            raise ValueError(f"unsupported phase: {next_phase}")
        previous = self.phase
        self.phase = next_phase
        self._log_phase_transition(previous=previous, current=next_phase)
        return self.phase

    def pause(self) -> None:
        self.paused = True
        self.logger.info(
            "operator paused runtime",
            extra={
                "event": "c07_operator_pause",
                "component": "c07",
                "phase": self.phase,
            },
        )

    def resume(self) -> None:
        self.paused = False
        self.logger.info(
            "operator resumed runtime",
            extra={
                "event": "c07_operator_resume",
                "component": "c07",
                "phase": self.phase,
            },
        )

    def run_cycle(
        self,
        *,
        source_image: str | Path,
        force_image_failure: bool = False,
    ) -> dict[str, Any]:
        if self.paused and self._last_dashboard_state is not None:
            paused = dict(self._last_dashboard_state)
            paused["paused"] = True
            paused["operator_message"] = "Runtime paused"
            self._write_dashboard_latest(paused)
            return paused

        self._cycle_index += 1
        cycle_id = f"c07-{self.phase}-{self._cycle_index:03d}"
        source = str(source_image)
        self._last_source_image = source

        vision_result = self.vision_pipeline.run_cycle(
            cycle_id=cycle_id,
            capture_source_image=source,
            retries=2,
            force_capture_failure=force_image_failure,
        )
        sensor_payload = self._build_sensor_payload(cycle_id=cycle_id, vision_result=vision_result)
        vision_payload = self._build_vision_payload(cycle_id=cycle_id, vision_result=vision_result)
        fused = self.fusion_service.fuse(cycle_id=cycle_id, sensor_payload=sensor_payload, vision_payload=vision_payload)

        self._last_sensor_payload = sensor_payload
        self._last_vision_payload = vision_payload
        self._last_vision_result = vision_result

        state = self._build_dashboard_state(
            cycle_id=cycle_id,
            sensor_payload=sensor_payload,
            vision_result=vision_result,
            fused=fused,
            paused=False,
        )
        self._last_dashboard_state = state
        self._write_cycle_artifacts(cycle_id=cycle_id, state=state)
        self._write_dashboard_latest(state)
        return state

    def recapture_image(self, *, source_image: str | Path | None = None) -> dict[str, Any]:
        chosen = str(source_image) if source_image is not None else self._last_source_image
        if chosen is None:
            raise ValueError("recapture requested without an image source")
        self.logger.info(
            "operator requested recapture",
            extra={"event": "c07_operator_recapture", "component": "c07", "phase": self.phase},
        )
        return self.run_cycle(source_image=chosen, force_image_failure=False)

    def force_recompute(self) -> dict[str, Any]:
        if self._last_sensor_payload is None or self._last_vision_payload is None or self._last_vision_result is None:
            raise RuntimeError("force_recompute requires at least one successful run_cycle")

        self._cycle_index += 1
        cycle_id = f"c07-{self.phase}-recompute-{self._cycle_index:03d}"
        sensor_payload = dict(self._last_sensor_payload)
        vision_payload = dict(self._last_vision_payload)
        sensor_payload["cycle_id"] = cycle_id
        vision_payload["cycle_id"] = cycle_id
        sensor_payload["timestamp"] = _ts()
        vision_payload["timestamp"] = _ts()

        self.logger.info(
            "operator forced recompute",
            extra={"event": "c07_operator_recompute", "component": "c07", "phase": self.phase},
        )

        fused = self.fusion_service.fuse(cycle_id=cycle_id, sensor_payload=sensor_payload, vision_payload=vision_payload)
        state = self._build_dashboard_state(
            cycle_id=cycle_id,
            sensor_payload=sensor_payload,
            vision_result=self._last_vision_result,
            fused=fused,
            paused=False,
        )
        self._last_dashboard_state = state
        self._write_cycle_artifacts(cycle_id=cycle_id, state=state)
        self._write_dashboard_latest(state)
        return state

    def _build_sensor_payload(self, *, cycle_id: str, vision_result: dict[str, Any]) -> dict[str, Any]:
        profile = PHASE_PROFILES[self.phase]
        degraded = bool(vision_result.get("degraded_mode", False))
        stale = bool(vision_result.get("stale", False) or "stale_result" in vision_result.get("quality_flags", []))
        confidence = profile.sensor_confidence_0_to_1
        if degraded or stale:
            confidence = max(0.25, confidence * 0.75)

        quality_flags = list(vision_result.get("quality_flags", []))
        if degraded and "vision_degraded_mode" not in quality_flags:
            quality_flags.append("vision_degraded_mode")

        uncertainty = ["deterministic_phase_profile"]
        if degraded:
            uncertainty.append("vision_degraded_mode")
        if stale:
            uncertainty.append("vision_stale")

        return {
            "timestamp": _ts(),
            "cycle_id": cycle_id,
            "rp_ohm": profile.rp_ohm,
            "current_ma": profile.current_ma,
            "status_band": profile.status_band,
            "electrochemical_severity_0_to_10": profile.sensor_severity_0_to_10,
            "confidence_0_to_1": round(confidence, 3),
            "key_findings": [f"phase={self.phase}", f"rp_ohm={profile.rp_ohm}", f"current_ma={profile.current_ma}"],
            "uncertainty_drivers": uncertainty,
            "quality_flags": sorted(set(quality_flags)),
            "degraded_mode": degraded,
            "stale": stale,
            "fallback_reason": str(vision_result.get("fallback_reason", "")),
            "model_id": "c07-deterministic-sensor-v1",
            "schema_version": "c05-sensor-v1",
        }

    @staticmethod
    def _build_vision_payload(*, cycle_id: str, vision_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "timestamp": str(vision_result.get("timestamp", _ts())),
            "cycle_id": cycle_id,
            "visual_severity_0_to_10": float(vision_result.get("visual_severity_0_to_10", 0.0)),
            "confidence_0_to_1": float(vision_result.get("confidence_0_to_1", 0.0)),
            "rust_coverage_band": str(vision_result.get("rust_coverage_band", "unknown")),
            "morphology_class": str(vision_result.get("morphology_class", "unknown")),
            "key_findings": list(vision_result.get("key_findings", ["vision_result_missing"])),
            "uncertainty_drivers": list(vision_result.get("uncertainty_drivers", ["vision_result_missing"])),
            "quality_flags": list(vision_result.get("quality_flags", [])),
            "degraded_mode": bool(vision_result.get("degraded_mode", False)),
            "stale": bool(vision_result.get("stale", False) or "stale_result" in vision_result.get("quality_flags", [])),
            "fallback_reason": str(vision_result.get("fallback_reason", "")),
            "model_id": "c04-vision-pipeline",
            "schema_version": "c05-vision-v1",
        }

    def _build_dashboard_state(
        self,
        *,
        cycle_id: str,
        sensor_payload: dict[str, Any],
        vision_result: dict[str, Any],
        fused: dict[str, Any],
        paused: bool,
    ) -> dict[str, Any]:
        degraded = bool(fused.get("degraded_mode", False))
        stale = bool(
            fused.get("stale", False)
            or vision_result.get("stale", False)
            or "stale_result" in vision_result.get("quality_flags", [])
        )
        state = {
            "timestamp": _ts(),
            "cycle_id": cycle_id,
            "phase": self.phase,
            "rp_ohm": float(sensor_payload.get("rp_ohm", 0.0)),
            "current_ma": float(sensor_payload.get("current_ma", 0.0)),
            "sensor_status_band": str(sensor_payload.get("status_band", "unknown")),
            "vision_severity_0_to_10": float(vision_result.get("visual_severity_0_to_10", 0.0)),
            "fused_severity_0_to_10": float(fused.get("fused_severity_0_to_10", 0.0)),
            "rul_days": float(fused.get("rul_days", 0.0)),
            "confidence_0_to_1": float(fused.get("confidence_0_to_1", 0.0)),
            "degraded_mode": degraded,
            "stale": stale,
            "vision_quality_flags": list(vision_result.get("quality_flags", [])),
            "paused": paused,
            "operator_controls": ["pause", "resume", "recapture image", "force recompute"],
            "phase_markers": list(PHASES),
            "disclaimer": "Educational prototype.",
        }
        state["ui"] = build_ui_state(state)
        return state

    def _write_cycle_artifacts(self, *, cycle_id: str, state: dict[str, Any]) -> None:
        json_path = self.session_dir / f"{cycle_id}.dashboard.json"
        html_path = self.session_dir / f"{cycle_id}.dashboard.html"
        json_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        html_path.write_text(render_dashboard_html(state), encoding="utf-8")

    def _write_dashboard_latest(self, state: dict[str, Any]) -> None:
        (self.session_dir / "dashboard-latest.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        (self.session_dir / "dashboard-latest.html").write_text(render_dashboard_html(state), encoding="utf-8")

    def _log_phase_transition(self, *, previous: str | None, current: str) -> None:
        self.logger.info(
            "c07 phase transition",
            extra={
                "event": "c07_phase_transition",
                "component": "c07",
                "phase_previous": previous or "none",
                "phase_current": current,
                "transition_timestamp": _ts(),
            },
        )


def build_ui_state(state: dict[str, Any]) -> dict[str, str | bool]:
    confidence = float(state.get("confidence_0_to_1", 0.0))
    degraded = bool(state.get("degraded_mode", False))
    stale = bool(state.get("stale", False))

    if confidence >= 0.8:
        confidence_label = "HIGH"
        confidence_color = "ok"
    elif confidence >= 0.5:
        confidence_label = "MEDIUM"
        confidence_color = "warn"
    else:
        confidence_label = "LOW"
        confidence_color = "critical"

    if degraded and stale:
        quality_label = "DEGRADED + STALE"
        quality_color = "critical"
    elif degraded:
        quality_label = "DEGRADED"
        quality_color = "warn"
    elif stale:
        quality_label = "STALE"
        quality_color = "warn"
    else:
        quality_label = "FRESH"
        quality_color = "ok"

    return {
        "confidence_label": confidence_label,
        "confidence_color": confidence_color,
        "quality_label": quality_label,
        "quality_color": quality_color,
    }


def render_dashboard_html(state: dict[str, Any]) -> str:
    ui = state.get("ui", {})
    phase = str(state.get("phase", "baseline"))
    markers = state.get("phase_markers", list(PHASES))

    phase_html = []
    for marker in markers:
        cls = "phase-pill active" if marker == phase else "phase-pill"
        phase_html.append(f'<span class="{cls}">{marker}</span>')

    quality_flags = state.get("vision_quality_flags", [])
    quality_text = ", ".join(quality_flags) if quality_flags else "none"

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>C07 Demo Dashboard</title>
  <style>
    :root {{
      --bg: #08131b;
      --panel: #122535;
      --panel2: #18354d;
      --text: #f3f7fb;
      --muted: #b3c8d8;
      --ok: #19d27c;
      --warn: #ffd447;
      --critical: #ff5b57;
      --accent: #3cb4ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      background: radial-gradient(circle at 20% 10%, #1c3650 0%, var(--bg) 45%), linear-gradient(120deg, #0a1722, #0b1d2b);
      font-family: "Trebuchet MS", "Segoe UI", sans-serif;
    }}
    .wrap {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 20px;
    }}
    .title {{
      font-size: clamp(1.4rem, 3vw, 2.4rem);
      font-weight: 800;
      letter-spacing: 0.02em;
    }}
    .subtitle {{ color: var(--muted); font-size: clamp(1rem, 2vw, 1.3rem); margin-top: 6px; }}
    .phases {{ margin-top: 14px; display: flex; gap: 10px; flex-wrap: wrap; }}
    .phase-pill {{
      border: 2px solid #4e6f86;
      border-radius: 999px;
      padding: 8px 14px;
      font-size: clamp(0.95rem, 1.8vw, 1.2rem);
      color: var(--muted);
    }}
    .phase-pill.active {{ border-color: var(--accent); color: #fff; background: rgba(60, 180, 255, 0.2); }}
    .grid {{
      margin-top: 16px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .card {{
      background: linear-gradient(180deg, var(--panel), var(--panel2));
      border: 1px solid #2f4f67;
      border-radius: 12px;
      padding: 14px;
      min-height: 108px;
    }}
    .label {{ color: var(--muted); font-size: clamp(0.9rem, 1.7vw, 1.1rem); }}
    .value {{ font-size: clamp(1.5rem, 3.1vw, 2.8rem); font-weight: 800; margin-top: 4px; }}
    .kpi {{ font-size: clamp(1rem, 1.8vw, 1.2rem); margin-top: 8px; color: var(--muted); }}
    .badge {{
      display: inline-block;
      border-radius: 999px;
      font-size: clamp(0.95rem, 1.7vw, 1.2rem);
      padding: 7px 12px;
      font-weight: 800;
      margin-top: 8px;
    }}
    .badge.ok {{ background: rgba(25, 210, 124, 0.2); color: var(--ok); border: 1px solid var(--ok); }}
    .badge.warn {{ background: rgba(255, 212, 71, 0.2); color: var(--warn); border: 1px solid var(--warn); }}
    .badge.critical {{ background: rgba(255, 91, 87, 0.2); color: var(--critical); border: 1px solid var(--critical); }}
    .controls {{ margin-top: 16px; display: flex; gap: 10px; flex-wrap: wrap; }}
    .controls button {{
      padding: 12px 16px;
      border-radius: 10px;
      border: 1px solid #3b5f77;
      background: #1f3d54;
      color: #fff;
      font-size: clamp(0.95rem, 1.8vw, 1.2rem);
      font-weight: 700;
    }}
    .disclaimer {{ margin-top: 14px; color: #ffdf7e; font-size: clamp(1rem, 1.9vw, 1.2rem); font-weight: 700; }}
    @media (max-width: 900px) {{
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 600px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .wrap {{ padding: 14px; }}
    }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"title\">Corrosion Demo Runtime Dashboard</div>
    <div class=\"subtitle\">Cycle: {state.get("cycle_id", "n/a")} | Timestamp: {state.get("timestamp", "n/a")}</div>
    <div class=\"phases\">{''.join(phase_html)}</div>

    <div class=\"grid\">
      <div class=\"card\"><div class=\"label\">Rp (ohm)</div><div class=\"value\">{state.get("rp_ohm", 0):,.0f}</div></div>
      <div class=\"card\"><div class=\"label\">Current (mA)</div><div class=\"value\">{state.get("current_ma", 0):.3f}</div></div>
      <div class=\"card\"><div class=\"label\">Sensor Status</div><div class=\"value\">{state.get("sensor_status_band", "n/a")}</div></div>
      <div class=\"card\"><div class=\"label\">Vision Severity</div><div class=\"value\">{state.get("vision_severity_0_to_10", 0):.2f}</div></div>
      <div class=\"card\"><div class=\"label\">Fused Severity</div><div class=\"value\">{state.get("fused_severity_0_to_10", 0):.2f}</div></div>
      <div class=\"card\"><div class=\"label\">RUL (days)</div><div class=\"value\">{state.get("rul_days", 0):.1f}</div></div>
      <div class=\"card\">
        <div class=\"label\">Confidence</div>
        <div class=\"value\">{state.get("confidence_0_to_1", 0):.2f}</div>
        <div class=\"badge {ui.get("confidence_color", "warn").lower()}\">{ui.get("confidence_label", "MEDIUM")}</div>
      </div>
      <div class=\"card\">
        <div class=\"label\">Data Quality</div>
        <div class=\"badge {ui.get("quality_color", "warn").lower()}\">{ui.get("quality_label", "UNKNOWN")}</div>
        <div class=\"kpi\">Vision Flags: {quality_text}</div>
      </div>
    </div>

    <div class=\"controls\">
      <button>pause</button>
      <button>resume</button>
      <button>recapture image</button>
      <button>force recompute</button>
    </div>

    <div class=\"disclaimer\">Educational prototype.</div>
  </div>
</body>
</html>
"""


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()
