#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fusion.c06 import FusionService
from fusion.c07 import C07Orchestrator
from vision.pipeline import VisionPipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSION_DIR = PROJECT_ROOT / "data" / "sessions" / "c07"
SUMMARY_PATH = SESSION_DIR / "c07-verification-summary.json"
LOG_PATH = PROJECT_ROOT / "data" / "logs" / "c07.log"
TEST_IMG_DIR = PROJECT_ROOT / "data" / "sessions" / "c04" / "test_images"


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _read_phase_transition_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") == "c07_phase_transition":
            events.append(payload)
    return events


def main() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "chunk": "C07",
        "timestamp": time.time(),
        "status": "pass",
        "tests": {},
        "limitations": [],
    }

    if LOG_PATH.exists():
        LOG_PATH.unlink()

    vp = VisionPipeline(PROJECT_ROOT, use_mock_camera=True)
    vp.calibrate_and_lock_profile()
    fusion = FusionService(PROJECT_ROOT, ml_advisory=None)
    runtime = C07Orchestrator(
        PROJECT_ROOT,
        vision_pipeline=vp,
        fusion_service=fusion,
    )

    runtime.transition_phase("acceleration")
    runtime.transition_phase("active")
    runtime.transition_phase("severe")
    runtime.transition_phase("fresh_swap")

    transitions = _read_phase_transition_events(LOG_PATH)
    _check(len(transitions) >= 5, "expected at least 5 phase transition log events")
    _check(all("transition_timestamp" in e for e in transitions), "transition log missing timestamp")
    report["tests"]["phase_transition_logging"] = {
        "pass": True,
        "events": len(transitions),
        "evidence": "data/logs/c07.log",
    }

    failed = runtime.run_cycle(source_image=TEST_IMG_DIR / "clean_1.jpg", force_image_failure=True)
    _check(failed["degraded_mode"] is True, "forced image failure did not set degraded mode")
    _check(
        failed.get("ui", {}).get("quality_label") in {"DEGRADED", "DEGRADED + STALE"},
        "forced image failure did not present degraded quality state",
    )

    recovered = runtime.recapture_image(source_image=TEST_IMG_DIR / "clean_1.jpg")
    _check(recovered["degraded_mode"] is False, "recapture did not recover degraded mode")
    _check(recovered["stale"] is False, "recapture did not clear stale")
    report["tests"]["operator_recover_from_image_failure"] = {
        "pass": True,
        "evidence": "data/sessions/c07/dashboard-latest.json",
    }

    ui = recovered.get("ui", {})
    _check(ui.get("confidence_label") in {"HIGH", "MEDIUM", "LOW"}, "missing confidence label")
    _check(ui.get("quality_label") == "FRESH", "recovered UI should report FRESH quality")
    report["tests"]["ui_state_degraded_stale_confidence"] = {
        "pass": True,
        "confidence_label": ui.get("confidence_label"),
        "quality_label": ui.get("quality_label"),
        "evidence": "data/sessions/c07/dashboard-latest.html",
    }

    latest_html = SESSION_DIR / "dashboard-latest.html"
    _check(latest_html.exists(), "dashboard html missing")
    html_content = latest_html.read_text(encoding="utf-8")
    _check("Educational prototype." in html_content, "disclaimer not found in dashboard html")
    report["tests"]["dashboard_disclaimer_present"] = {
        "pass": True,
        "evidence": "data/sessions/c07/dashboard-latest.html",
    }

    overall = all(test.get("pass", False) for test in report["tests"].values())
    report["status"] = "pass" if overall else "fail"

    SUMMARY_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    if not overall:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
