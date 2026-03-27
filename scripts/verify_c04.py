#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from vision.pipeline import VisionPipeline, VisionResult


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSION_DIR = PROJECT_ROOT / "data" / "sessions" / "c04"
TEST_IMG_DIR = SESSION_DIR / "test_images"


def _expect(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def _validate_schema(payload: dict) -> None:
    VisionResult.model_validate(payload)


def _expect_capture_artifacts(cycle_id: str) -> None:
    capture = SESSION_DIR / "captures" / f"{cycle_id}.jpg"
    meta = SESSION_DIR / "captures" / f"{cycle_id}.meta.json"
    _expect(capture.exists(), f"missing JPEG capture for {cycle_id}")
    _expect(meta.exists(), f"missing capture metadata for {cycle_id}")
    m = json.loads(meta.read_text(encoding="utf-8"))
    _expect(m.get("image_format") == "jpeg", f"invalid image format in metadata for {cycle_id}")


def main() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "chunk": "C04",
        "timestamp": time.time(),
        "tests": {},
        "status": "pass",
        "limitations": [],
    }

    vp = VisionPipeline(PROJECT_ROOT, use_mock_camera=True)
    calib = vp.calibrate_and_lock_profile()
    report["calibration_profile"] = str(calib.relative_to(PROJECT_ROOT))

    # 1) Quality gate rejects blurred
    blurred = vp.run_cycle("t_blur", TEST_IMG_DIR / "blurred.jpg")
    _validate_schema(blurred)
    _expect("blur_too_high" in blurred["quality_flags"], "blur gate failed")
    report["tests"]["quality_blur_reject"] = {
        "pass": True,
        "evidence": "data/sessions/c04/results/t_blur.json",
    }

    # 2) Exposure rejects under/over
    over = vp.run_cycle("t_over", TEST_IMG_DIR / "overexposed.jpg")
    under = vp.run_cycle("t_under", TEST_IMG_DIR / "underexposed.jpg")
    _validate_schema(over)
    _validate_schema(under)
    _expect("overexposed" in over["quality_flags"], "overexposed gate failed")
    _expect("underexposed" in under["quality_flags"], "underexposed gate failed")
    report["tests"]["quality_exposure_reject"] = {
        "pass": True,
        "evidence": "data/sessions/c04/results/t_over.json, data/sessions/c04/results/t_under.json",
    }

    # 3) Valid schema on clean image
    clean = vp.run_cycle("t_clean_schema", TEST_IMG_DIR / "clean_1.jpg")
    _validate_schema(clean)
    _expect(clean["rust_coverage_band"] in {"none", "light", "moderate", "heavy"}, "invalid rust band")
    _expect(isinstance(clean.get("key_findings"), list) and len(clean["key_findings"]) > 0, "missing key findings")
    _expect(isinstance(clean.get("uncertainty_drivers"), list) and len(clean["uncertainty_drivers"]) > 0, "missing uncertainty drivers")
    _expect_capture_artifacts("t_clean_schema")
    report["tests"]["valid_image_schema"] = {
        "pass": True,
        "evidence": "data/sessions/c04/results/t_clean_schema.json",
    }

    report["tests"]["jpeg_capture_with_cycle_metadata"] = {
        "pass": True,
        "evidence": "data/sessions/c04/captures/t_clean_schema.jpg, data/sessions/c04/captures/t_clean_schema.meta.json",
    }

    # 4) Degraded mode fallback on forced capture fail
    # seed a last-valid result first
    vp.run_cycle("t_seed_valid", TEST_IMG_DIR / "clean_2.jpg")
    degraded = vp.run_cycle("t_forced_fail", force_capture_failure=True)
    _validate_schema(degraded)
    _expect(degraded["degraded_mode"] is True, "degraded mode not enabled")
    _expect(degraded["fallback_reason"] == "capture_failed_retries_exhausted", "wrong fallback reason")
    _expect("stale_result" in degraded["quality_flags"], "stale fallback flag missing")
    report["tests"]["degraded_mode_fallback"] = {
        "pass": True,
        "evidence": "data/sessions/c04/results/t_forced_fail.json",
    }

    # 4b) Quality gate retries then falls back to stale result
    quality_fallback = vp.run_cycle("t_quality_fail", TEST_IMG_DIR / "blurred.jpg", retries=2)
    _validate_schema(quality_fallback)
    _expect(quality_fallback["degraded_mode"] is True, "quality retry fallback did not degrade")
    _expect(
        quality_fallback["fallback_reason"] == "quality_gate_failed_retries_exhausted",
        "wrong quality fallback reason",
    )
    _expect("blur_too_high" in quality_fallback["quality_flags"], "quality flag missing in quality fallback")
    _expect("stale_result" in quality_fallback["quality_flags"], "stale fallback flag missing in quality fallback")
    report["tests"]["quality_retry_exhaustion_fallback"] = {
        "pass": True,
        "evidence": "data/sessions/c04/results/t_quality_fail.json",
    }

    # 5) Trend sanity test
    clean_scores = []
    corr_scores = []
    for i in range(6):
        c = vp.run_cycle(f"trend_clean_{i}", TEST_IMG_DIR / ("clean_1.jpg" if i % 2 == 0 else "clean_2.jpg"))
        r = vp.run_cycle(f"trend_corr_{i}", TEST_IMG_DIR / ("corroded_1.jpg" if i % 2 == 0 else "corroded_2.jpg"))
        clean_scores.append(c["visual_severity_0_to_10"])
        corr_scores.append(r["visual_severity_0_to_10"])

    clean_avg = statistics.fmean(clean_scores)
    corr_avg = statistics.fmean(corr_scores)
    _expect(corr_avg > clean_avg, "trend sanity failed: corroded severity not higher")
    report["tests"]["trend_sanity"] = {
        "pass": True,
        "clean_avg": round(clean_avg, 3),
        "corroded_avg": round(corr_avg, 3),
        "evidence": "data/sessions/c04/results/trend_*.json",
    }

    # Latency target check
    all_results = []
    for p in sorted((SESSION_DIR / "results").glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if "latency_ms" in data:
            all_results.append(data["latency_ms"])
    median_latency = statistics.median(all_results) if all_results else 0
    report["tests"]["latency_median_target"] = {
        "pass": median_latency <= 10000,
        "median_latency_ms": median_latency,
        "target_ms": 10000,
        "evidence": "data/sessions/c04/results/*.json",
    }

    # Accelerated robustness simulation as CI-safe replacement for camera endurance
    start = time.perf_counter()
    for i in range(300):
        if i % 17 == 0:
            vp.run_cycle(f"robust_fail_{i}", force_capture_failure=True)
        else:
            img = TEST_IMG_DIR / ("corroded_1.jpg" if i % 3 == 0 else "clean_1.jpg")
            vp.run_cycle(f"robust_{i}", img)
    elapsed = time.perf_counter() - start
    report["tests"]["accelerated_robustness_simulation"] = {
        "pass": True,
        "cycles": 300,
        "elapsed_seconds": round(elapsed, 2),
        "evidence": "data/sessions/c04/results/robust_*.json",
    }
    report["limitations"].append(
        "Physical 1-hour camera endurance on Pi HQ hardware not executed in CI; accelerated robustness simulation executed instead."
    )

    overall_pass = all(item.get("pass", False) for item in report["tests"].values())
    report["status"] = "pass" if overall_pass else "fail"

    out = SESSION_DIR / "c04-verification-summary.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    if not overall_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
