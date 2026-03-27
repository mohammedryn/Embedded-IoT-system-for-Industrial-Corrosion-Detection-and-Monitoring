from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from fusion.gateway import validate_before_fusion
from fusion.specialists import AISettings, PromptTemplates, SpecialistService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ScriptedClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate(self, *, model_id: str, prompt: str, timeout_seconds: float) -> str:
        self.calls.append(
            {
                "model_id": model_id,
                "prompt": prompt,
                "timeout_seconds": timeout_seconds,
            }
        )
        if not self.responses:
            raise RuntimeError("no scripted response")
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


def _sensor_valid_json(cycle_id: str) -> str:
    return json.dumps(
        {
            "timestamp": "2026-03-28T10:00:00+00:00",
            "cycle_id": cycle_id,
            "rp_ohm": 61000.0,
            "current_ma": 0.11,
            "status_band": "HEALTHY",
            "electrochemical_severity_0_to_10": 1.2,
            "confidence_0_to_1": 0.91,
            "key_findings": ["rp_high_healthy_band"],
            "uncertainty_drivers": ["none"],
            "quality_flags": [],
            "degraded_mode": False,
            "stale": False,
            "fallback_reason": "",
            "model_id": "ignored_by_service",
            "schema_version": "ignored_by_service",
        }
    )


def _vision_valid_json(cycle_id: str) -> str:
    return json.dumps(
        {
            "timestamp": "2026-03-28T10:00:01+00:00",
            "cycle_id": cycle_id,
            "visual_severity_0_to_10": 2.1,
            "confidence_0_to_1": 0.85,
            "rust_coverage_band": "light",
            "morphology_class": "uniform",
            "key_findings": ["light_rust_visible"],
            "uncertainty_drivers": ["none"],
            "quality_flags": [],
            "degraded_mode": False,
            "stale": False,
            "fallback_reason": "",
            "model_id": "ignored_by_service",
            "schema_version": "ignored_by_service",
        }
    )


class TestC05Specialists(unittest.TestCase):
    def test_valid_schema_output_and_fusion_gate(self) -> None:
        client = ScriptedClient([_sensor_valid_json("cyc-1"), _vision_valid_json("cyc-1")])
        svc = SpecialistService(PROJECT_ROOT, client, settings=_settings(), sleep_fn=lambda _: None)

        sensor = svc.run_sensor(
            cycle_id="cyc-1",
            sensor_input={"rp_ohm": 61000.0, "current_ma": 0.11, "status_band": "HEALTHY"},
        )
        vision = svc.run_vision(
            cycle_id="cyc-1",
            vision_input={"visual_severity_0_to_10": 2.1, "rust_coverage_band": "light", "morphology_class": "uniform"},
        )
        validated = validate_before_fusion(sensor_payload=sensor, vision_payload=vision)

        self.assertEqual(validated["sensor"]["cycle_id"], "cyc-1")
        self.assertEqual(validated["vision"]["cycle_id"], "cyc-1")
        self.assertEqual(validated["sensor"]["model_id"], "gemini-3-flash-preview")
        self.assertEqual(validated["vision"]["model_id"], "gemini-3-flash-preview")

    def test_malformed_output_recovery(self) -> None:
        client = ScriptedClient(["not-json", _sensor_valid_json("cyc-2")])
        svc = SpecialistService(PROJECT_ROOT, client, settings=_settings(max_attempts=2), sleep_fn=lambda _: None)

        result = svc.run_sensor(
            cycle_id="cyc-2",
            sensor_input={"rp_ohm": 55000.0, "current_ma": 0.14, "status_band": "HEALTHY"},
        )
        self.assertFalse(result["degraded_mode"])
        self.assertFalse(result["stale"])
        self.assertEqual(len(client.calls), 2)

    def test_timeout_and_retry_uses_fallback_model(self) -> None:
        client = ScriptedClient([TimeoutError("t1"), TimeoutError("t2"), _vision_valid_json("cyc-3")])
        svc = SpecialistService(PROJECT_ROOT, client, settings=_settings(max_attempts=3), sleep_fn=lambda _: None)

        result = svc.run_vision(
            cycle_id="cyc-3",
            vision_input={"visual_severity_0_to_10": 3.5, "rust_coverage_band": "moderate", "morphology_class": "localized"},
        )
        self.assertFalse(result["degraded_mode"])
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(client.calls[0]["model_id"], "gemini-3-flash-preview")
        self.assertEqual(client.calls[1]["model_id"], "gemini-3-flash-preview")
        self.assertEqual(client.calls[2]["model_id"], "gemini-3.1-pro-preview")
        self.assertEqual(result["model_id"], "gemini-3.1-pro-preview")

    def test_stale_fallback_behavior(self) -> None:
        client = ScriptedClient([_sensor_valid_json("seed"), "bad", TimeoutError("down")])
        svc = SpecialistService(PROJECT_ROOT, client, settings=_settings(max_attempts=2), sleep_fn=lambda _: None)

        seed = svc.run_sensor(
            cycle_id="seed",
            sensor_input={"rp_ohm": 40000.0, "current_ma": 0.25, "status_band": "WARNING"},
        )
        self.assertFalse(seed["degraded_mode"])

        stale = svc.run_sensor(
            cycle_id="cyc-4",
            sensor_input={"rp_ohm": 30000.0, "current_ma": 0.35, "status_band": "WARNING"},
        )
        self.assertTrue(stale["degraded_mode"])
        self.assertTrue(stale["stale"])
        self.assertIn("stale_result", stale["quality_flags"])
        self.assertIn("stale_fallback_used", stale["uncertainty_drivers"])

    def test_prompt_templates_are_deterministic(self) -> None:
        a = {"b": 2, "a": 1}
        b = {"a": 1, "b": 2}
        self.assertEqual(PromptTemplates.build_sensor_prompt(a), PromptTemplates.build_sensor_prompt(b))


if __name__ == "__main__":
    unittest.main()
