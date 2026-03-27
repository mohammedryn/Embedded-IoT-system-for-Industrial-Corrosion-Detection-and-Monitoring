#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fusion.gateway import validate_before_fusion
from fusion.specialists import AISettings, SpecialistService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSION_DIR = PROJECT_ROOT / "data" / "sessions" / "c05"
SUMMARY_PATH = SESSION_DIR / "c05-verification-summary.json"


class ScriptedClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate(self, *, model_id: str, prompt: str, timeout_seconds: float) -> str:
        self.calls.append({"model_id": model_id, "timeout_seconds": timeout_seconds, "prompt_size": len(prompt)})
        if not self.responses:
            raise RuntimeError("no scripted responses left")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return str(nxt)


def _settings(max_attempts: int = 3) -> AISettings:
    return AISettings(
        primary_model_id="gemini-3-flash-preview",
        fallback_model_id="gemini-3.1-pro-preview",
        response_mode="json",
        max_attempts=max_attempts,
        timeout_seconds=0.01,
        backoff_seconds=0.0,
    )


def _sensor_valid(cycle_id: str) -> str:
    return json.dumps(
        {
            "timestamp": "2026-03-28T10:00:00+00:00",
            "cycle_id": cycle_id,
            "rp_ohm": 50000.0,
            "current_ma": 0.2,
            "status_band": "HEALTHY",
            "electrochemical_severity_0_to_10": 1.5,
            "confidence_0_to_1": 0.9,
            "key_findings": ["healthy_profile"],
            "uncertainty_drivers": ["none"],
            "quality_flags": [],
            "degraded_mode": False,
            "stale": False,
            "fallback_reason": "",
            "model_id": "ignored",
            "schema_version": "ignored",
        }
    )


def _vision_valid(cycle_id: str) -> str:
    return json.dumps(
        {
            "timestamp": "2026-03-28T10:00:01+00:00",
            "cycle_id": cycle_id,
            "visual_severity_0_to_10": 3.2,
            "confidence_0_to_1": 0.84,
            "rust_coverage_band": "moderate",
            "morphology_class": "localized",
            "key_findings": ["patch_growth_detected"],
            "uncertainty_drivers": ["none"],
            "quality_flags": [],
            "degraded_mode": False,
            "stale": False,
            "fallback_reason": "",
            "model_id": "ignored",
            "schema_version": "ignored",
        }
    )


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "chunk": "C05",
        "timestamp": time.time(),
        "status": "pass",
        "tests": {},
    }

    # 1) Valid schema output and pre-fusion validation gate
    client1 = ScriptedClient([_sensor_valid("c05-valid"), _vision_valid("c05-valid")])
    svc1 = SpecialistService(PROJECT_ROOT, client1, settings=_settings(), sleep_fn=lambda _: None)
    sensor = svc1.run_sensor(cycle_id="c05-valid", sensor_input={"rp_ohm": 50000.0, "current_ma": 0.2, "status_band": "HEALTHY"})
    vision = svc1.run_vision(
        cycle_id="c05-valid",
        vision_input={"visual_severity_0_to_10": 3.2, "confidence_0_to_1": 0.84, "rust_coverage_band": "moderate", "morphology_class": "localized"},
    )
    validated = validate_before_fusion(sensor_payload=sensor, vision_payload=vision)
    _check(validated["sensor"]["model_id"] == "gemini-3-flash-preview", "wrong primary model in sensor output")
    _check(validated["vision"]["model_id"] == "gemini-3-flash-preview", "wrong primary model in vision output")
    report["tests"]["valid_schema_output"] = {
        "pass": True,
        "evidence": "strict JSON accepted and schema-validated before fusion",
    }

    # 2) Malformed output recovery
    client2 = ScriptedClient(["bad-output", _sensor_valid("c05-malformed")])
    svc2 = SpecialistService(PROJECT_ROOT, client2, settings=_settings(max_attempts=2), sleep_fn=lambda _: None)
    recovered = svc2.run_sensor(
        cycle_id="c05-malformed",
        sensor_input={"rp_ohm": 45000.0, "current_ma": 0.25, "status_band": "WARNING"},
    )
    _check(recovered["degraded_mode"] is False, "malformed output did not recover")
    _check(len(client2.calls) == 2, "malformed recovery did not retry")
    report["tests"]["malformed_output_recovery"] = {
        "pass": True,
        "attempts": len(client2.calls),
        "evidence": "bad JSON recovered by retry",
    }

    # 3) Timeout + retry behavior with fallback model
    client3 = ScriptedClient([TimeoutError("t1"), TimeoutError("t2"), _vision_valid("c05-timeout")])
    svc3 = SpecialistService(PROJECT_ROOT, client3, settings=_settings(max_attempts=3), sleep_fn=lambda _: None)
    timeout_recovered = svc3.run_vision(
        cycle_id="c05-timeout",
        vision_input={"visual_severity_0_to_10": 4.0, "confidence_0_to_1": 0.7, "rust_coverage_band": "moderate", "morphology_class": "uniform"},
    )
    _check(len(client3.calls) == 3, "timeout retry attempts mismatch")
    _check(client3.calls[-1]["model_id"] == "gemini-3.1-pro-preview", "fallback model was not used")
    _check(timeout_recovered["model_id"] == "gemini-3.1-pro-preview", "output model does not match fallback model")
    report["tests"]["timeout_retry_behavior"] = {
        "pass": True,
        "attempts": len(client3.calls),
        "models": [c["model_id"] for c in client3.calls],
        "evidence": "timeouts retried and recovered on fallback model",
    }

    # 4) Stale fallback behavior
    client4 = ScriptedClient([_sensor_valid("c05-seed"), "bad", TimeoutError("api down")])
    svc4 = SpecialistService(PROJECT_ROOT, client4, settings=_settings(max_attempts=2), sleep_fn=lambda _: None)
    seed = svc4.run_sensor(cycle_id="c05-seed", sensor_input={"rp_ohm": 42000.0, "current_ma": 0.3, "status_band": "WARNING"})
    _check(seed["degraded_mode"] is False, "seed response should be valid")
    stale = svc4.run_sensor(cycle_id="c05-stale", sensor_input={"rp_ohm": 38000.0, "current_ma": 0.35, "status_band": "WARNING"})
    _check(stale["degraded_mode"] is True, "stale fallback did not enable degraded_mode")
    _check(stale["stale"] is True, "stale fallback flag missing")
    _check("stale_result" in stale["quality_flags"], "stale_result quality flag missing")
    report["tests"]["stale_fallback_behavior"] = {
        "pass": True,
        "evidence": "last-known-valid response reused with stale flags",
    }

    all_pass = all(t.get("pass", False) for t in report["tests"].values())
    report["status"] = "pass" if all_pass else "fail"

    SUMMARY_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    if not all_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
