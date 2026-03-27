from __future__ import annotations

import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fusion.c07 import C07Orchestrator, build_ui_state, render_dashboard_html


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class FakeVisionPipeline:
    def run_cycle(
        self,
        cycle_id: str,
        capture_source_image: str,
        retries: int = 2,
        force_capture_failure: bool = False,
    ) -> dict[str, Any]:
        _ = retries
        if force_capture_failure:
            return {
                "timestamp": "2026-03-28T00:00:00+00:00",
                "cycle_id": cycle_id,
                "visual_severity_0_to_10": 6.5,
                "confidence_0_to_1": 0.35,
                "rust_coverage_band": "heavy",
                "morphology_class": "localized",
                "key_findings": ["capture_failed"],
                "uncertainty_drivers": ["capture_failed"],
                "quality_flags": ["capture_failed", "stale_result"],
                "degraded_mode": True,
                "stale": True,
                "fallback_reason": "capture_failed_retries_exhausted",
                "source_image": capture_source_image,
            }

        return {
            "timestamp": "2026-03-28T00:00:01+00:00",
            "cycle_id": cycle_id,
            "visual_severity_0_to_10": 2.4,
            "confidence_0_to_1": 0.9,
            "rust_coverage_band": "light",
            "morphology_class": "uniform",
            "key_findings": ["clean"],
            "uncertainty_drivers": ["none"],
            "quality_flags": [],
            "degraded_mode": False,
            "stale": False,
            "fallback_reason": "",
            "source_image": capture_source_image,
        }


class FakeFusionService:
    def fuse(self, *, cycle_id: str, sensor_payload: dict[str, Any], vision_payload: dict[str, Any]) -> dict[str, Any]:
        sensor_sev = float(sensor_payload["electrochemical_severity_0_to_10"])
        vision_sev = float(vision_payload["visual_severity_0_to_10"])
        degraded = bool(sensor_payload.get("degraded_mode", False) or vision_payload.get("degraded_mode", False))
        stale = bool(sensor_payload.get("stale", False) or vision_payload.get("stale", False))
        confidence = (float(sensor_payload["confidence_0_to_1"]) * 0.6) + (float(vision_payload["confidence_0_to_1"]) * 0.4)
        if degraded or stale:
            confidence *= 0.75

        return {
            "timestamp": "2026-03-28T00:00:02+00:00",
            "cycle_id": cycle_id,
            "fused_severity_0_to_10": round((sensor_sev * 0.6) + (vision_sev * 0.4), 4),
            "rul_days": round(365.0 - ((sensor_sev * 0.6) + (vision_sev * 0.4)) * 30.0, 2),
            "confidence_0_to_1": round(min(1.0, max(0.0, confidence)), 4),
            "degraded_mode": degraded,
            "stale": stale,
        }


class TestC07Orchestration(unittest.TestCase):
    def test_phase_transition_logging(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            logger = logging.getLogger("test.c07.phase")
            logger.setLevel(logging.INFO)
            logger.handlers.clear()
            handler = ListHandler()
            logger.addHandler(handler)
            logger.propagate = False

            orchestrator = C07Orchestrator(
                root,
                vision_pipeline=FakeVisionPipeline(),
                fusion_service=FakeFusionService(),
                logger=logger,
            )

            orchestrator.transition_phase("active")
            orchestrator.transition_phase("severe")

            phase_events = [r for r in handler.records if getattr(r, "event", "") == "c07_phase_transition"]
            self.assertGreaterEqual(len(phase_events), 3)
            self.assertTrue(all(hasattr(r, "transition_timestamp") for r in phase_events))
            self.assertEqual(getattr(phase_events[-2], "phase_current"), "active")
            self.assertEqual(getattr(phase_events[-1], "phase_current"), "severe")

    def test_operator_recovers_after_image_failure_without_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = C07Orchestrator(
                root,
                vision_pipeline=FakeVisionPipeline(),
                fusion_service=FakeFusionService(),
            )

            failed = orchestrator.run_cycle(source_image="synthetic.jpg", force_image_failure=True)
            self.assertTrue(failed["degraded_mode"])
            self.assertTrue(failed["stale"])

            recovered = orchestrator.recapture_image(source_image="synthetic.jpg")
            self.assertFalse(recovered["degraded_mode"])
            self.assertFalse(recovered["stale"])
            self.assertGreater(recovered["confidence_0_to_1"], failed["confidence_0_to_1"])

    def test_ui_state_reflects_degraded_stale_and_confidence(self) -> None:
        healthy = build_ui_state({"confidence_0_to_1": 0.9, "degraded_mode": False, "stale": False})
        degraded = build_ui_state({"confidence_0_to_1": 0.42, "degraded_mode": True, "stale": True})

        self.assertEqual(healthy["confidence_label"], "HIGH")
        self.assertEqual(healthy["quality_label"], "FRESH")
        self.assertEqual(degraded["confidence_label"], "LOW")
        self.assertEqual(degraded["quality_label"], "DEGRADED + STALE")

        html = render_dashboard_html(
            {
                "cycle_id": "c07-demo-001",
                "timestamp": "2026-03-28T00:00:00+00:00",
                "phase": "active",
                "phase_markers": ["baseline", "acceleration", "active", "severe", "fresh_swap"],
                "rp_ohm": 45000.0,
                "current_ma": 0.22,
                "sensor_status_band": "WARNING",
                "vision_severity_0_to_10": 4.2,
                "fused_severity_0_to_10": 4.5,
                "rul_days": 200.0,
                "confidence_0_to_1": 0.42,
                "degraded_mode": True,
                "stale": True,
                "vision_quality_flags": ["stale_result"],
                "ui": degraded,
            }
        )
        self.assertIn("Educational prototype.", html)
        self.assertIn("pause", html)
        self.assertIn("resume", html)
        self.assertIn("recapture image", html)
        self.assertIn("force recompute", html)


if __name__ == "__main__":
    unittest.main()
