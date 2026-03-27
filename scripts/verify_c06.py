#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fusion.c06 import FusionService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSION_DIR = PROJECT_ROOT / "data" / "sessions" / "c06"
SUMMARY_PATH = SESSION_DIR / "c06-verification-summary.json"


class StaticAdvisory:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict_rul_days(self, *, features: dict[str, Any]) -> float:
        _ = features
        return self.value


def _sensor(
    *,
    sev: float,
    conf: float = 0.9,
    degraded: bool = False,
    stale: bool = False,
) -> dict[str, Any]:
    return {
        "timestamp": "2026-03-28T12:00:00+00:00",
        "cycle_id": "seed",
        "rp_ohm": 50000.0,
        "current_ma": 0.2,
        "status_band": "HEALTHY",
        "electrochemical_severity_0_to_10": sev,
        "confidence_0_to_1": conf,
        "key_findings": ["sensor_ok"],
        "uncertainty_drivers": ["none"],
        "quality_flags": [],
        "degraded_mode": degraded,
        "stale": stale,
        "fallback_reason": "",
        "model_id": "gemini-3-flash-preview",
        "schema_version": "c05-sensor-v1",
    }


def _vision(
    *,
    sev: float,
    conf: float = 0.85,
    degraded: bool = False,
    stale: bool = False,
) -> dict[str, Any]:
    return {
        "timestamp": "2026-03-28T12:00:01+00:00",
        "cycle_id": "seed",
        "visual_severity_0_to_10": sev,
        "confidence_0_to_1": conf,
        "rust_coverage_band": "light",
        "morphology_class": "uniform",
        "key_findings": ["vision_ok"],
        "uncertainty_drivers": ["none"],
        "quality_flags": [],
        "degraded_mode": degraded,
        "stale": stale,
        "fallback_reason": "",
        "model_id": "gemini-3-flash-preview",
        "schema_version": "c05-vision-v1",
    }


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "chunk": "C06",
        "timestamp": time.time(),
        "status": "pass",
        "tests": {},
    }

    # 1) Agreement scenario
    svc1 = FusionService(PROJECT_ROOT, ml_advisory=StaticAdvisory(240.0))
    out1 = svc1.fuse(cycle_id="c06-agreement", sensor_payload=_sensor(sev=2.0), vision_payload=_vision(sev=2.3))
    _check(out1["conflict_detected"] is False, "agreement scenario unexpectedly marked conflict")
    report["tests"]["agreement_scenario"] = {
        "pass": True,
        "evidence": "stable fusion output with no conflict",
    }

    # 2) Conflict scenario
    svc2 = FusionService(PROJECT_ROOT, ml_advisory=StaticAdvisory(170.0))
    out2 = svc2.fuse(cycle_id="c06-conflict", sensor_payload=_sensor(sev=8.0), vision_payload=_vision(sev=2.0))
    _check(out2["conflict_detected"] is True, "conflict scenario not detected")
    _check("conflict detected" in out2["rationale"], "conflict rationale missing")
    report["tests"]["conflict_scenario"] = {
        "pass": True,
        "evidence": "delta>3 detected and rationale populated",
    }

    # 3) Noise robustness
    svc3 = FusionService(PROJECT_ROOT, ml_advisory=StaticAdvisory(210.0))
    a = svc3.fuse(cycle_id="c06-noise-a", sensor_payload=_sensor(sev=3.0), vision_payload=_vision(sev=3.0))
    b = svc3.fuse(cycle_id="c06-noise-b", sensor_payload=_sensor(sev=3.1), vision_payload=_vision(sev=2.9))
    _check(abs(a["fused_severity_0_to_10"] - b["fused_severity_0_to_10"]) <= 0.12, "noise robustness threshold violated")
    report["tests"]["noise_robustness"] = {
        "pass": True,
        "evidence": "small perturbations do not create unstable jumps",
    }

    # 4) ML override scenario
    svc4 = FusionService(PROJECT_ROOT, ml_advisory=StaticAdvisory(9000.0))
    out4 = svc4.fuse(cycle_id="c06-ml-override", sensor_payload=_sensor(sev=6.0), vision_payload=_vision(sev=5.2))
    _check(out4["ml_advisory_used"] is True, "ml advisory should be marked used")
    _check(out4["ml_override_reason"] == "ml_advisory_overridden_implausible_value", "override reason mismatch")
    report["tests"]["ml_override_scenario"] = {
        "pass": True,
        "evidence": "implausible advisory overridden with explicit reason",
    }

    # 5) Missing ML model fallback
    svc5 = FusionService(PROJECT_ROOT, ml_advisory=None)
    out5 = svc5.fuse(cycle_id="c06-ml-missing", sensor_payload=_sensor(sev=4.0), vision_payload=_vision(sev=4.2))
    _check(out5["ml_advisory_used"] is False, "missing ML should disable advisory")
    _check(out5["ml_override_reason"] == "ml_unavailable_fallback_heuristic", "missing ML fallback reason mismatch")
    report["tests"]["ml_missing_fallback"] = {
        "pass": True,
        "evidence": "deterministic heuristic used when ML unavailable",
    }

    # 6) Degraded and stale propagation
    svc6 = FusionService(PROJECT_ROOT, ml_advisory=StaticAdvisory(190.0))
    out6 = svc6.fuse(
        cycle_id="c06-degraded-stale",
        sensor_payload=_sensor(sev=5.0, degraded=True, stale=True),
        vision_payload=_vision(sev=5.5),
    )
    _check(out6["degraded_mode"] is True, "degraded flag did not propagate")
    _check(out6["stale"] is True, "stale flag did not propagate")
    report["tests"]["degraded_stale_propagation"] = {
        "pass": True,
        "evidence": "upstream degraded/stale flags preserved in fused output",
    }

    overall = all(test.get("pass", False) for test in report["tests"].values())
    report["status"] = "pass" if overall else "fail"

    SUMMARY_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not overall:
        raise SystemExit(1)


if __name__ == "__main__":
    main()