from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from fusion.c06 import FusionService, FusionSettings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


class TestC06Fusion(unittest.TestCase):
    def test_agreement_no_conflict(self) -> None:
        svc = FusionService(PROJECT_ROOT, ml_advisory=StaticAdvisory(240.0))
        out = svc.fuse(cycle_id="c06-agree", sensor_payload=_sensor(sev=2.0), vision_payload=_vision(sev=2.4))

        self.assertFalse(out["conflict_detected"])
        self.assertAlmostEqual(out["fused_severity_0_to_10"], 2.16, places=2)
        self.assertTrue(out["ml_advisory_used"])
        self.assertIsNone(out["ml_override_reason"])
        self.assertFalse(out["degraded_mode"])

    def test_conflict_with_rationale(self) -> None:
        svc = FusionService(PROJECT_ROOT, ml_advisory=StaticAdvisory(180.0))
        out = svc.fuse(cycle_id="c06-conflict", sensor_payload=_sensor(sev=8.0), vision_payload=_vision(sev=2.0))

        self.assertTrue(out["conflict_detected"])
        self.assertGreater(out["severity_delta"], 3.0)
        self.assertIn("conflict detected", out["rationale"])

    def test_noise_robustness_small_perturbation(self) -> None:
        svc = FusionService(PROJECT_ROOT, ml_advisory=StaticAdvisory(200.0))
        a = svc.fuse(cycle_id="c06-noise-a", sensor_payload=_sensor(sev=3.0), vision_payload=_vision(sev=3.0))
        b = svc.fuse(cycle_id="c06-noise-b", sensor_payload=_sensor(sev=3.1), vision_payload=_vision(sev=2.9))

        self.assertLessEqual(abs(a["fused_severity_0_to_10"] - b["fused_severity_0_to_10"]), 0.12)

    def test_ml_override_with_reason(self) -> None:
        svc = FusionService(PROJECT_ROOT, ml_advisory=StaticAdvisory(9000.0))
        out = svc.fuse(cycle_id="c06-override", sensor_payload=_sensor(sev=6.0), vision_payload=_vision(sev=5.0))

        self.assertTrue(out["ml_advisory_used"])
        self.assertEqual(out["ml_override_reason"], "ml_advisory_overridden_implausible_value")
        self.assertIn("ml_override_applied", out["uncertainty_drivers"])

    def test_missing_ml_model_fallback_path(self) -> None:
        svc = FusionService(PROJECT_ROOT, ml_advisory=None)
        out = svc.fuse(cycle_id="c06-no-ml", sensor_payload=_sensor(sev=4.0), vision_payload=_vision(sev=4.5))

        self.assertFalse(out["ml_advisory_used"])
        self.assertEqual(out["ml_override_reason"], "ml_unavailable_fallback_heuristic")

    def test_degraded_stale_propagation(self) -> None:
        svc = FusionService(
            PROJECT_ROOT,
            ml_advisory=StaticAdvisory(190.0),
            settings=FusionSettings(sensor_weight=0.6, vision_weight=0.4, conflict_delta_threshold=3.0),
        )
        out = svc.fuse(
            cycle_id="c06-degraded",
            sensor_payload=_sensor(sev=4.0, degraded=True, stale=True),
            vision_payload=_vision(sev=4.2),
        )

        self.assertTrue(out["degraded_mode"])
        self.assertTrue(out["stale"])
        self.assertIn("upstream_degraded_mode", out["uncertainty_drivers"])
        self.assertIn("upstream_stale", out["uncertainty_drivers"])


if __name__ == "__main__":
    unittest.main()