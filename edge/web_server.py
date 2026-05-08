#!/usr/bin/env python3
import base64
import concurrent.futures
import io
import json
import http.server
import os
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
import uuid as _uuid
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from edge.serial_reader import (
    DEFAULT_BAUD,
    DEFAULT_PORT,
    SerialConnectionError,
    SerialFrameReader,
)
from edge.session_state import session_state

PORT = 8080

# Paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "web"
SESSION_DIR = PROJECT_ROOT / "data" / "sessions" / "c07"
DASHBOARD_JSON = SESSION_DIR / "dashboard-latest.json"

SSE_HEARTBEAT_SECONDS = 5.0

serial_reader = SerialFrameReader(port=DEFAULT_PORT, baud=DEFAULT_BAUD, max_frames=2000)

# Lazy-initialised heavy services (vision pipeline + fusion) — created on first analyze call.
_svc_lock = threading.Lock()
_vision_pipeline = None
_fusion_service = None
_ai_provider = None
_specialist_service = None
_specialist_init_error = ""


class _CameraPreviewWorker:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._process = None
        self._latest_frame = None
        self._latest_frame_time = 0.0
        self._running = False
        self._buffer = bytearray()
        self._start_error = ""

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            self._running = False
            process = self._process
            self._process = None
        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass

    def status(self):
        with self._lock:
            return {
                "running": self._running,
                "ready": self._latest_frame is not None,
                "age_seconds": round(time.time() - self._latest_frame_time, 3) if self._latest_frame_time else None,
                "error": self._start_error,
            }

    def latest_frame(self):
        with self._lock:
            return self._latest_frame, self._latest_frame_time, self._start_error

    def _run(self):
        camera_bins = [candidate for candidate in ("rpicam-vid", "libcamera-vid") if shutil.which(candidate)]
        if not camera_bins:
            with self._lock:
                self._start_error = "rpicam-vid / libcamera-vid not found"
                self._running = False
            return

        cmd = [
            camera_bins[0],
            "-n",
            "-t",
            "0",
            "--codec",
            "mjpeg",
            "--low-latency",
            "--framerate",
            "12",
            "--width",
            "640",
            "--height",
            "360",
            "-o",
            "-",
        ]

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception as exc:
            with self._lock:
                self._start_error = str(exc)
                self._running = False
            return

        with self._lock:
            self._process = process
            self._start_error = ""

        stdout = process.stdout
        if stdout is None:
            with self._lock:
                self._start_error = "camera preview stdout unavailable"
                self._running = False
            return

        soi = b"\xff\xd8"
        eoi = b"\xff\xd9"

        try:
            while True:
                with self._lock:
                    if not self._running:
                        break

                if hasattr(stdout, "read1"):
                    chunk = stdout.read1(65536)
                else:
                    chunk = stdout.read(65536)
                if not chunk:
                    break

                self._buffer.extend(chunk)
                while True:
                    start = self._buffer.find(soi)
                    if start < 0:
                        if len(self._buffer) > 2:
                            self._buffer[:] = self._buffer[-1:]
                        break
                    end = self._buffer.find(eoi, start + 2)
                    if end < 0:
                        if start > 0:
                            del self._buffer[:start]
                        break

                    frame = bytes(self._buffer[start:end + 2])
                    del self._buffer[:end + 2]
                    with self._lock:
                        self._latest_frame = frame
                        self._latest_frame_time = time.time()
        finally:
            try:
                process.terminate()
            except Exception:
                pass
            with self._lock:
                self._process = None
                self._running = False


_camera_preview_worker = _CameraPreviewWorker()


def _get_vision_pipeline():
    global _vision_pipeline
    if _vision_pipeline is None:
        with _svc_lock:
            if _vision_pipeline is None:
                from vision.pipeline import VisionPipeline
                _vision_pipeline = VisionPipeline(project_root=PROJECT_ROOT, use_mock_camera=True)
    return _vision_pipeline


def _get_fusion_service():
    global _fusion_service
    if _fusion_service is None:
        with _svc_lock:
            if _fusion_service is None:
                from fusion.c06 import FusionService
                _fusion_service = FusionService(project_root=str(PROJECT_ROOT))
    return _fusion_service


def _get_ai_provider():
    global _ai_provider
    if _ai_provider is None:
        with _svc_lock:
            if _ai_provider is None:
                from ai.providers.local import LocalHeuristicProvider
                from ai.providers.vertex import VertexAIProvider
                from ai.runtime import load_ai_config

                config = load_ai_config(PROJECT_ROOT)
                if config.provider == "vertex":
                    _ai_provider = VertexAIProvider(config=config)
                else:
                    _ai_provider = LocalHeuristicProvider(config=config)
    return _ai_provider


def _get_specialist_service():
    """Return a SpecialistService wired to the active provider when cloud mode is usable."""
    global _specialist_service, _specialist_init_error
    provider = _get_ai_provider()
    runtime = provider.describe_runtime()
    if runtime.get("runtime_mode") != "vertex_expert":
        _specialist_init_error = runtime.get("degraded_reason", "") or runtime.get("auth_source", "cloud_unavailable")
        return None

    if _specialist_service is None:
        with _svc_lock:
            if _specialist_service is None:
                try:
                    from fusion.specialists import SpecialistService, load_ai_settings

                    _specialist_service = SpecialistService(
                        project_root=PROJECT_ROOT,
                        client=provider,
                        settings=load_ai_settings(PROJECT_ROOT),
                    )
                    _specialist_init_error = ""
                except Exception as exc:
                    _specialist_init_error = f"init_failed:{type(exc).__name__}"
    return _specialist_service


def _analysis_runtime_meta(svc) -> dict:
    provider = _get_ai_provider()
    runtime = dict(provider.describe_runtime())
    mode = str(runtime.get("runtime_mode", "local_heuristic"))

    if svc is not None:
        payloads = getattr(svc, "_latest_runtime_payloads", None) or {}
        any_degraded = any(bool((payloads.get(key) or {}).get("degraded_mode", False)) for key in ("sensor", "vision", "final"))
        if mode == "vertex_expert" and any_degraded:
            mode = "vertex_degraded"

    message = {
        "vertex_expert": "Vertex specialists enabled",
        "vertex_degraded": "Vertex analysis degraded; deterministic fallbacks were used for part of the request",
        "local_heuristic": "Cloud analysis unavailable; using local heuristic mode",
    }.get(mode, "AI runtime unknown")

    return {
        "mode": mode,
        "provider": str(runtime.get("provider", "local_heuristic")),
        "auth_mode": str(runtime.get("auth_mode", "disabled")),
        "auth_source": str(runtime.get("auth_source", "none")),
        "project_id": str(runtime.get("project_id", "")),
        "location": str(runtime.get("location", "global")),
        "cloud_enabled": bool(runtime.get("cloud_enabled", False)),
        "circuit_breaker_open": bool(runtime.get("circuit_breaker_open", False)),
        "specialists_ready": svc is not None,
        "message": message,
        "degraded_reason": str(runtime.get("degraded_reason", "")),
    }


def _ensure_camera_preview_worker():
    _camera_preview_worker.start()


def _best_vision_result(photos: list, cycle_id: str) -> dict | None:
    """Run VisionPipeline on photos and return the highest-confidence result, or None."""
    best_result = None
    best_conf = -1.0
    vp = _get_vision_pipeline()
    for photo in photos:
        try:
            result = vp.analyze_image(photo["path"], cycle_id)
            if not result.get("quality_flags") and result.get("confidence_0_to_1", 0) > best_conf:
                best_result = result
                best_conf = result["confidence_0_to_1"]
        except Exception:
            pass
    if best_result is None and photos:
        try:
            best_result = vp.analyze_image(photos[-1]["path"], cycle_id)
        except Exception:
            pass
    return best_result


def _best_vision_observation(photos: list, cycle_id: str) -> tuple[dict | None, dict | None]:
    """Return (best_result, source_photo) for the most useful photo in the session."""
    best_result = None
    best_photo = None
    best_conf = -1.0
    vp = _get_vision_pipeline()
    for photo in photos:
        try:
            result = vp.analyze_image(photo["path"], cycle_id)
            quality_flags = result.get("quality_flags") or []
            confidence = float(result.get("confidence_0_to_1", 0.0) or 0.0)
            if not quality_flags and confidence > best_conf:
                best_result = result
                best_photo = photo
                best_conf = confidence
        except Exception:
            pass
    if best_result is None and photos:
        try:
            best_photo = photos[-1]
            best_result = vp.analyze_image(best_photo["path"], cycle_id)
        except Exception:
            pass
    return best_result, best_photo


def _load_source_catalog() -> dict[str, dict]:
    try:
        from fusion.specialists import load_corrosion_memory
        memory = load_corrosion_memory(PROJECT_ROOT)
        return {
            str(item.get("id")): {
                "id": str(item.get("id")),
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "source_type": str(item.get("source_type", "")),
            }
            for item in memory.source_memory
            if item.get("id")
        }
    except Exception:
        return {}


def _expand_sources(source_ids: list[str]) -> list[dict]:
    catalog = _load_source_catalog()
    expanded: list[dict] = []
    seen: set[str] = set()
    for source_id in source_ids:
        if source_id in seen:
            continue
        seen.add(source_id)
        meta = catalog.get(source_id)
        if meta:
            expanded.append(meta)
        else:
            expanded.append({"id": source_id, "title": source_id, "url": "", "source_type": ""})
    return expanded


def _map_gemini_image_result_to_vision_payload(
    gemini_result: dict,
    local_result: dict,
    cycle_id: str,
) -> dict:
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()
    morphology = str(gemini_result.get("surface_condition", local_result.get("morphology_class", "unknown")))
    pit_suspected = bool(gemini_result.get("pitting_observed", False)) or (
        "pitted" in morphology.lower()
    )
    key_findings = list(local_result.get("key_findings", [])) + list(gemini_result.get("key_findings", []))
    quality_flags = list(local_result.get("quality_flags", []))
    uncertainty_drivers = list(local_result.get("uncertainty_drivers", []))
    uncertainty_drivers.extend(gemini_result.get("surface_limitations", []))
    surface_summary = gemini_result.get(
        "text_summary",
        "Gemini visual review was unavailable; local vision metrics were used instead.",
    )
    suspected_damage_modes = gemini_result.get("suspected_damage_modes", [])
    suspicious_regions = gemini_result.get("suspicious_regions", [])
    if suspicious_regions:
        suspected_damage_modes = list(suspected_damage_modes) + [f"regions:{', '.join(suspicious_regions)}"]
    return {
        "timestamp": timestamp,
        "cycle_id": cycle_id,
        "visual_severity_0_to_10": float(gemini_result.get("severity_0_to_10", local_result.get("visual_severity_0_to_10", 5.0))),
        "confidence_0_to_1": float(gemini_result.get("confidence_0_to_1", local_result.get("confidence_0_to_1", 0.3))),
        "rust_coverage_band": str(gemini_result.get("rust_coverage_estimate", local_result.get("rust_coverage_band", "unknown"))),
        "morphology_class": morphology,
        "surface_summary": surface_summary,
        "pit_suspected": pit_suspected,
        "pit_evidence": str(gemini_result.get("pitting_evidence", "not_reported")),
        "suspected_damage_modes": suspected_damage_modes or ["unknown"],
        "key_findings": key_findings or ["no_valid_visual_signal"],
        "recommended_actions": list(gemini_result.get("recommendations", [])) or [
            "Capture sharper, evenly lit close-up images before trusting fine pitting interpretation.",
        ],
        "source_ids": [
            "orientjchem_neutral_chloride_2019",
            "corsci_metastable_pitting_304_2014",
            "ma_2022_sensitized_304_acid_chloride",
        ],
        "uncertainty_drivers": uncertainty_drivers or ["image_ai_limited"],
        "quality_flags": quality_flags,
        "degraded_mode": bool(local_result.get("degraded_mode", False)),
        "stale": False,
        "fallback_reason": local_result.get("fallback_reason", ""),
        "model_id": str(gemini_result.get("model_id", "gemini-vision")),
        "schema_version": "c05-vision-v1",
        "gemini_raw": gemini_result,
    }


def _build_cloud_vision_prompt(context: dict) -> str:
    return f"""You are a corrosion-vision specialist reviewing a steel or stainless-steel surface image.
Return STRICT JSON only (no markdown, no prose, no code fences).

Use cautious corrosion language and preserve the local visual summary when uncertain.

Return exactly this schema:
{{
  "text_summary": "2-4 sentence technical description of what the surface visually suggests",
  "rust_coverage_estimate": "none|light|moderate|heavy",
  "surface_condition": "uniform|pitted|localized|mixed|other",
  "severity_0_to_10": 3.5,
  "confidence_0_to_1": 0.85,
  "pitting_observed": false,
  "pitting_evidence": "brief explanation",
  "suspected_damage_modes": ["mode1", "mode2"],
  "suspicious_regions": ["region1", "region2"],
  "corrosion_spot_count_estimate": "none|few|several|many|unknown",
  "surface_limitations": ["limitation1"],
  "key_findings": ["finding1", "finding2", "finding3"],
  "recommendations": ["recommendation1", "recommendation2"],
  "model_id": "the model id that produced this answer"
}}

Context JSON:
{json.dumps(context, sort_keys=True, indent=2)}
"""


def _ai_vision_payload_from_photos(photos: list, cycle_id: str, provider=None, timeout_seconds: float = 15.0) -> dict:
    raw, source_photo = _best_vision_observation(photos, cycle_id)
    if raw is None:
        return _no_vision_payload(cycle_id)

    provider = provider or _get_ai_provider()
    runtime = provider.describe_runtime() if provider is not None else {"runtime_mode": "local_heuristic"}
    if source_photo is None or runtime.get("runtime_mode") != "vertex_expert" or not hasattr(provider, "analyze_image_with_context"):
        payload = _build_vision_payload(raw, cycle_id)
        return payload

    try:
        context = {
            "cycle_id": cycle_id,
            "project_mode": "corrosion_lab_surface_assessment",
            "local_vision_summary": raw,
            "photo_count": len(photos),
            "research_hint": "Interpret chloride-exposed steel or stainless steel cautiously with respect to localized attack.",
        }
        response_text = provider.analyze_image_with_context(
            image_path=source_photo["path"],
            prompt=_build_cloud_vision_prompt(context),
            model_id=str(runtime.get("primary_model_id", runtime.get("fallback_model_id", "gemini-2.5-flash"))),
            timeout_seconds=timeout_seconds,
        )
        gemini_result = json.loads(response_text)
        if not isinstance(gemini_result, dict):
            raise ValueError("cloud vision response root is not an object")
        if "error" in gemini_result:
            payload = _build_vision_payload(raw, cycle_id)
            payload["fallback_reason"] = f"gemini_vision_error:{gemini_result.get('error', 'unknown')}"
            return payload
        return _map_gemini_image_result_to_vision_payload(gemini_result, raw, cycle_id)
    except Exception as exc:
        payload = _build_vision_payload(raw, cycle_id)
        payload["fallback_reason"] = f"gemini_vision_exception:{type(exc).__name__}"
        return payload


def _rp_to_severity(rp_ohm: float) -> float:
    if rp_ohm <= 0:
        return 9.5
    if rp_ohm < 500:
        return 9.5
    if rp_ohm < 1000:
        return 9.0
    if rp_ohm < 5000:
        return 8.0
    if rp_ohm < 10000:
        return 6.5
    if rp_ohm < 20000:
        return 5.0
    if rp_ohm < 50000:
        return 3.0
    if rp_ohm < 100000:
        return 1.5
    return 0.5


def _build_sensor_payload(readings: list, cycle_id: str) -> dict:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    if not readings:
        return {
            "timestamp": now, "cycle_id": cycle_id,
            "rp_ohm": 0.0, "current_ma": 0.0, "status_band": "unknown",
            "electrochemical_severity_0_to_10": 5.0, "confidence_0_to_1": 0.1,
            "key_findings": ["no_readings_collected"],
            "uncertainty_drivers": ["empty_dataset"],
            "quality_flags": ["no_data"],
            "degraded_mode": True, "stale": False,
            "fallback_reason": "no_readings",
            "model_id": "heuristic-v1", "schema_version": "c05-sensor-v1",
        }
    rp_values = [r["rp_ohm"] for r in readings if r.get("rp_ohm", 0) > 0]
    current_values = [r.get("current_ua", 0.0) for r in readings]
    mean_rp = sum(rp_values) / len(rp_values) if rp_values else 0.0
    mean_current_ua = sum(current_values) / len(current_values) if current_values else 0.0
    if len(rp_values) > 1:
        mean_sq = sum((v - mean_rp) ** 2 for v in rp_values) / len(rp_values)
        std_rp = mean_sq ** 0.5
    else:
        std_rp = 0.0
    last_status = readings[-1].get("status", "UNKNOWN").lower() if readings else "unknown"
    severity = _rp_to_severity(mean_rp)
    count = len(readings)
    confidence = min(0.95, 0.3 + count * 0.065)
    quality_flags = []
    uncertainty_drivers = []
    if mean_rp > 0 and std_rp > mean_rp * 0.1:
        quality_flags.append("high_variance")
        uncertainty_drivers.append("reading_variance_high")
    if count < 5:
        uncertainty_drivers.append("few_readings")
    return {
        "timestamp": now, "cycle_id": cycle_id,
        "rp_ohm": round(mean_rp, 2),
        "current_ma": round(mean_current_ua / 1000.0, 4),
        "status_band": last_status,
        "electrochemical_severity_0_to_10": round(severity, 2),
        "confidence_0_to_1": round(confidence, 3),
        "expert_summary": (
            f"Mean Rp was {round(mean_rp, 1)} ohm over {count} readings; this is being treated as a comparative corrosion-resistance indicator."
        ),
        "mechanistic_interpretation": (
            "Heuristic mode treats higher Rp as lower overall corrosion activity, but does not convert Rp into an absolute corrosion rate because Stern-Geary calibration and exposed-area rigor are not available here."
        ),
        "corrosion_mode": (
            "passive_or_low_activity" if mean_rp >= 50000 else
            "mild_activity" if mean_rp >= 10000 else
            "active_corrosion" if mean_rp >= 1000 else
            "severe_active_corrosion"
        ),
        "key_findings": [
            f"mean_rp={round(mean_rp, 1)}_ohm",
            f"n={count}_readings",
            f"status={last_status}",
        ],
        "recommended_actions": [
            "Use the averaged late-cycle readings as a relative baseline, not as an absolute corrosion-rate certificate.",
            "Compare against repeat runs and controlled chloride/agitation changes to confirm trend direction.",
        ],
        "source_ids": [
            "metrohm_an_cor_003_2025",
            "gonzalez_b_catalog_1996",
            "cemconcomp_lpr_limitations_2006",
        ],
        "uncertainty_drivers": uncertainty_drivers or ["none"],
        "quality_flags": quality_flags,
        "degraded_mode": False, "stale": False, "fallback_reason": "",
        "model_id": "heuristic-v1", "schema_version": "c05-sensor-v1",
    }


def _build_vision_payload(vision_result: dict, cycle_id: str) -> dict:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    return {
        "timestamp": vision_result.get("timestamp", now),
        "cycle_id": cycle_id,
        "visual_severity_0_to_10": vision_result.get("visual_severity_0_to_10", 5.0),
        "confidence_0_to_1": vision_result.get("confidence_0_to_1", 0.3),
        "rust_coverage_band": vision_result.get("rust_coverage_band", "unknown"),
        "morphology_class": vision_result.get("morphology_class", "unknown"),
        "surface_summary": vision_result.get(
            "surface_summary",
            "Local HSV-based vision review was used to estimate visible rust and surface morphology."
        ),
        "pit_suspected": bool(vision_result.get("pit_suspected", False)),
        "pit_evidence": vision_result.get("pit_evidence", "not_assessed"),
        "suspected_damage_modes": vision_result.get("suspected_damage_modes", ["unknown"]),
        "key_findings": vision_result.get("key_findings", ["local_hsv_analysis"]),
        "recommended_actions": vision_result.get(
            "recommended_actions",
            ["Capture multiple sharp images with oblique lighting if pit confirmation is important."]
        ),
        "source_ids": vision_result.get(
            "source_ids",
            ["orientjchem_neutral_chloride_2019", "corsci_metastable_pitting_304_2014"]
        ),
        "uncertainty_drivers": vision_result.get("uncertainty_drivers", ["local_only"]),
        "quality_flags": vision_result.get("quality_flags", []),
        "degraded_mode": vision_result.get("degraded_mode", False),
        "stale": False,
        "fallback_reason": vision_result.get("fallback_reason", ""),
        "model_id": "vision-local-hsv-v1",
        "schema_version": "c05-vision-v1",
    }


def _fmt_ohm(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} MOhm"
    if value >= 1_000:
        return f"{value / 1_000:.1f} kOhm"
    return f"{value:.0f} Ohm"


def _fmt_current_ma(value_ma: float) -> str:
    ua = value_ma * 1000.0
    if abs(ua) >= 1000.0:
        return f"{value_ma:.3f} mA"
    return f"{ua:.3f} uA"


def _extract_count_from_findings(findings: list[str]) -> int | None:
    for item in findings:
        if item.startswith("n=") and item.endswith("_readings"):
            try:
                return int(item[2:].split("_", 1)[0])
            except ValueError:
                return None
    return None


def _electrochemical_band(rp_ohm: float) -> tuple[str, str]:
    if rp_ohm <= 0:
        return (
            "invalid_response",
            "The reported polarization resistance is non-physical, which usually indicates wiring, polarity, or cell instability.",
        )
    if rp_ohm < 1_000:
        return (
            "severe_active_corrosion",
            "The polarization resistance is extremely low, which is consistent with aggressive active corrosion or a major setup fault.",
        )
    if rp_ohm < 5_000:
        return (
            "active_corrosion",
            "The polarization resistance is low and consistent with active corrosion rather than a passive surface.",
        )
    if rp_ohm < 10_000:
        return (
            "moderate_corrosion",
            "The polarization resistance suggests moderate corrosion activity and loss of passivity.",
        )
    if rp_ohm < 50_000:
        return (
            "mild_to_moderate_activity",
            "The polarization resistance suggests mild to moderate electrochemical activity. The surface is not as passive as fresh healthy steel.",
        )
    if rp_ohm < 100_000:
        return (
            "passive_to_mild_activity",
            "The polarization resistance is in a healthy range for this project and is more consistent with a mostly passive surface than active corrosion.",
        )
    return (
        "strongly_passive_surface",
        "The polarization resistance is very high for this setup, which is consistent with a strongly passive or only minimally corroding surface.",
    )


def _build_analysis_report(
    *,
    sensor_payload: dict,
    vision_payload: dict,
    fused_payload: dict,
    input_counts: dict[str, int],
    ai_runtime: dict,
) -> dict:
    rp_ohm = float(sensor_payload.get("rp_ohm", 0.0) or 0.0)
    current_ma = float(sensor_payload.get("current_ma", 0.0) or 0.0)
    status_band = str(sensor_payload.get("status_band", "unknown"))
    sensor_conf = float(sensor_payload.get("confidence_0_to_1", 0.0) or 0.0)
    vision_conf = float(vision_payload.get("confidence_0_to_1", 0.0) or 0.0)
    fused_conf = float(fused_payload.get("confidence_0_to_1", 0.0) or 0.0)
    fused_severity = float(fused_payload.get("fused_severity_0_to_10", 0.0) or 0.0)
    rul_days = float(fused_payload.get("rul_days", 0.0) or 0.0)
    conflict = bool(fused_payload.get("conflict_detected", False))
    sensor_quality = list(sensor_payload.get("quality_flags", []))
    sensor_uncertainty = list(sensor_payload.get("uncertainty_drivers", []))
    vision_quality = list(vision_payload.get("quality_flags", []))
    rust_band = str(vision_payload.get("rust_coverage_band", "unknown"))
    morphology = str(vision_payload.get("morphology_class", "unknown"))
    reading_count = _extract_count_from_findings(list(sensor_payload.get("key_findings", []))) or int(input_counts.get("readings", 0))
    photo_count = int(input_counts.get("photos", 0))

    electrochem_label, electrochem_text = _electrochemical_band(rp_ohm)
    ai_mode = str(ai_runtime.get("mode", "unknown"))

    overview = (
        f"Mean polarization resistance was {_fmt_ohm(rp_ohm)} with mean response current {_fmt_current_ma(current_ma)}. "
        f"The fused severity score was {fused_severity:.2f}/10 with estimated remaining useful life of {rul_days:.1f} days."
    )

    electrochem_points = [
        f"Status band reported by the measurement engine: {status_band}.",
        electrochem_text,
        f"For this project, an Rp of {_fmt_ohm(rp_ohm)} is much closer to the passive/healthy end than to the active-corrosion end.",
    ]
    if current_ma != 0.0:
        electrochem_points.append(
            f"The measured current amplitude was {_fmt_current_ma(current_ma)}, which is small and consistent with low electrochemical activity."
        )

    surface_points = [
        f"Vision pipeline classified rust coverage as {rust_band} and morphology as {morphology}.",
        "If the sample is freshly cleaned steel, this low-rust interpretation is directionally consistent with the electrochemical reading."
        if rust_band in {"none", "low", "unknown"} else
        "Surface evidence suggests visible corrosion features that should be compared carefully against the electrochemical trend.",
    ]
    if conflict:
        surface_points.append("Sensor and vision results disagree enough to trigger a conflict condition, so the corrosion state should be interpreted cautiously.")
    else:
        surface_points.append("No major sensor-versus-vision conflict was detected in the fusion stage.")

    quality_points = [
        f"Analysis used {reading_count} reading(s) and {photo_count} photo(s).",
        f"Sensor confidence was {sensor_conf * 100:.0f}%, vision confidence was {vision_conf * 100:.0f}%, and fused confidence was {fused_conf * 100:.0f}%.",
        f"AI runtime mode was {ai_mode.replace('_', ' ')}.",
    ]
    if sensor_quality:
        quality_points.append("Sensor quality flags: " + ", ".join(sensor_quality) + ".")
    if vision_quality:
        quality_points.append("Vision quality flags: " + ", ".join(vision_quality) + ".")
    if sensor_uncertainty and sensor_uncertainty != ["none"]:
        quality_points.append("Electrochemical uncertainty drivers: " + ", ".join(sensor_uncertainty) + ".")
    if ai_mode != "vertex_expert":
        quality_points.append(
            "This report is being generated from a degraded or local heuristic pathway rather than the full Vertex specialist pathway, so the interpretation is more deterministic than expert-like."
        )

    recommendation_points = []
    if electrochem_label in {"strongly_passive_surface", "passive_to_mild_activity"}:
        recommendation_points.extend([
            "Treat this run as a healthy baseline candidate and save the averaged last 5 stable readings.",
            "Repeat the run after re-immersion or after adding a controlled corrosive stimulus so you can demonstrate a downward Rp trend.",
        ])
    else:
        recommendation_points.extend([
            "Repeat the test after confirming electrode roles, solution salinity, and immersion geometry.",
            "Capture a second run after the cell has settled for at least 3 full cycles before drawing conclusions.",
        ])
    if status_band == "unknown" or rp_ohm <= 0:
        recommendation_points.append("Do not use this run as a report-quality result until the electrochemical response is physically plausible and repeatable.")
    if photo_count == 0:
        recommendation_points.append("Capture at least one sharp surface image so the report can cross-check electrochemistry against visible corrosion evidence.")

    conclusion = (
        f"Overall interpretation: the sample currently appears {('largely passive with low corrosion activity' if fused_severity < 3.0 else 'electrochemically active enough to warrant caution')}. "
        f"The present result should be reported as {'a baseline-quality healthy reading' if fused_severity < 3.0 else 'an active-corrosion reading requiring repeat confirmation'}."
    )

    source_ids = list(dict.fromkeys(
        list(sensor_payload.get("source_ids", [])) + list(vision_payload.get("source_ids", []))
    ))

    return {
        "headline": "Electrochemical Corrosion Assessment",
        "overview": overview,
        "conclusion": conclusion,
        "sections": [
            {"title": "Electrochemical Interpretation", "items": electrochem_points},
            {"title": "Surface Correlation", "items": surface_points},
            {"title": "Data Quality and Confidence", "items": quality_points},
            {"title": "Recommended Next Actions", "items": recommendation_points},
        ],
        "source_ids": source_ids,
        "sources": _expand_sources(source_ids),
    }


def _no_vision_payload(cycle_id: str) -> dict:
    from datetime import datetime, timezone
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "visual_severity_0_to_10": 5.0, "confidence_0_to_1": 0.1,
        "rust_coverage_band": "unknown", "morphology_class": "unknown",
        "surface_summary": "No photos were available for visual corrosion assessment.",
        "pit_suspected": False,
        "pit_evidence": "no_photos",
        "suspected_damage_modes": ["unknown"],
        "key_findings": ["no_photos_captured"],
        "recommended_actions": ["Capture at least one clear surface image before requesting final corrosion interpretation."],
        "source_ids": ["orientjchem_neutral_chloride_2019", "corsci_metastable_pitting_304_2014"],
        "uncertainty_drivers": ["no_images"],
        "quality_flags": ["no_photos"],
        "degraded_mode": True, "stale": False,
        "fallback_reason": "no_photos",
        "model_id": "heuristic-v1", "schema_version": "c05-vision-v1",
    }


def _mark_payload_degraded(payload: dict, fallback_reason: str) -> dict:
    degraded = dict(payload)
    degraded["degraded_mode"] = True
    degraded["fallback_reason"] = fallback_reason
    degraded.setdefault("stale", False)
    uncertainty = list(degraded.get("uncertainty_drivers", []))
    if fallback_reason and fallback_reason not in uncertainty:
        uncertainty.append(fallback_reason)
    if "uncertainty_drivers" in degraded:
        degraded["uncertainty_drivers"] = uncertainty
    return degraded


def _default_state_payload():
    return {
        "cycle_id": "waiting",
        "phase": "baseline",
        "rp_ohm": 65000,
        "current_ma": 0.15,
        "sensor_status_band": "healthy",
        "vision_severity_0_to_10": 1.5,
        "fused_severity_0_to_10": 1.6,
        "rul_days": 310.5,
        "confidence_0_to_1": 0.85,
        "degraded_mode": False,
        "stale": False,
        "vision_quality_flags": [],
        "paused": False,
        "phase_markers": ["baseline", "acceleration", "active", "severe", "fresh_swap"],
    }


def _load_dashboard_payload():
    if not DASHBOARD_JSON.exists():
        return _default_state_payload()

    text = DASHBOARD_JSON.read_text(encoding="utf-8").strip()
    if not text:
        return _default_state_payload()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some writers append multiple JSON objects to the same file.
        # Decode the first valid object so /api/state remains available.
        try:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(text)
            return obj
        except json.JSONDecodeError:
            print(f"Warning: malformed dashboard JSON in {DASHBOARD_JSON}; using default state")
            return _default_state_payload()


def _frame_to_payload(frame):
    return {
        "seq": frame.seq,
        "timestamp": frame.timestamp,
        "timestamp_unix": frame.timestamp_unix,
        "rp_ohm": frame.rp_ohm,
        "current_ua": frame.current_ua,
        "status": frame.status,
        "asym_percent": frame.asym_percent,
        "raw": frame.raw,
    }


def _ingest_frame(frame):
    session_state.add_reading(_frame_to_payload(frame))


serial_reader.register_callback(_ingest_frame)


class ThreadingReuseTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class DashboardServerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/api/state":
            self._serve_state()
            return
        if route == "/api/session/readings":
            self._session_readings()
            return
        if route == "/api/session/readings/stream":
            self._session_readings_stream(parsed.query)
            return
        if route == "/api/session/photos":
            self._session_photos()
            return
        if route == "/api/session/camera/preview":
            self._session_camera_preview()
            return
        if route == "/api/session/camera/stream":
            self._session_camera_stream()
            return

        super().do_GET()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        route = parsed.path
        if route.startswith("/api/session/photos/"):
            photo_id = route[len("/api/session/photos/"):]
            self._session_photo_delete(photo_id)
            return
        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/api/control":
            self._handle_control()
            return
        if route == "/api/session/new":
            self._session_new()
            return
        if route == "/api/session/serial/connect":
            self._session_serial_connect()
            return
        if route == "/api/session/serial/disconnect":
            self._session_serial_disconnect()
            return
        if route == "/api/session/capture":
            self._session_capture()
            return
        if route == "/api/session/analyze":
            self._session_analyze()
            return

        self.send_error(404, "Not Found")

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_jpeg(self, image_bytes: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(image_bytes)))
        self.end_headers()
        self.wfile.write(image_bytes)

    def _send_mjpeg_frame(self, image_bytes: bytes):
        boundary = b"--frame"
        header = (
            boundary + b"\r\n"
            + b"Content-Type: image/jpeg\r\n"
            + f"Content-Length: {len(image_bytes)}\r\n\r\n".encode("utf-8")
        )
        self.wfile.write(header)
        self.wfile.write(image_bytes)
        self.wfile.write(b"\r\n")

    def _session_camera_stream(self):
        _ensure_camera_preview_worker()

        deadline = time.time() + 10.0
        frame = None
        frame_time = 0.0
        start_error = ""
        while time.time() < deadline:
            frame, frame_time, start_error = _camera_preview_worker.latest_frame()
            if frame is not None:
                break
            if start_error:
                self._send_json(503, {"ok": False, "error": "camera_not_available", "detail": start_error})
                return
            time.sleep(0.1)

        if frame is None:
            self._send_json(504, {"ok": False, "error": "camera_timeout", "detail": "camera preview did not become ready"})
            return

        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        last_sent_time = 0.0
        try:
            while True:
                frame, frame_time, _ = _camera_preview_worker.latest_frame()
                if frame is not None and frame_time > last_sent_time:
                    self._send_mjpeg_frame(frame)
                    self.wfile.flush()
                    last_sent_time = frame_time
                else:
                    time.sleep(0.08)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _serve_state(self):
        payload = _load_dashboard_payload()
        self._send_json(200, payload)

    def _handle_control(self):
        try:
            req = self._read_json_body()
            action = req.get("action")
            print(f">>> UI Control Received: {action}")
            self._send_json(200, {"status": "ok", "action": action})
        except Exception as exc:
            self._send_json(400, {"status": "error", "message": str(exc)})

    def _session_new(self):
        session_id = session_state.new_session()
        self._send_json(
            201,
            {
                "ok": True,
                "session_id": session_id,
                "photos_count": len(session_state.list_photos()),
                "readings_count": len(session_state.readings_snapshot()),
            },
        )

    def _session_serial_connect(self):
        try:
            body = self._read_json_body()
            port = body.get("port", DEFAULT_PORT)
            baud = int(body.get("baud", DEFAULT_BAUD))
            if baud <= 0:
                self._send_json(400, {"ok": False, "error": "invalid_baud"})
                return

            serial_reader.connect(port=port, baud=baud)
            self._send_json(
                200,
                {
                    "ok": True,
                    "serial_connected": serial_reader.is_connected(),
                    "port": port,
                    "baud": baud,
                },
            )
        except SerialConnectionError as exc:
            self._send_json(502, {"ok": False, "error": "serial_connect_failed", "detail": str(exc)})
        except Exception as exc:
            self._send_json(400, {"ok": False, "error": "bad_request", "detail": str(exc)})

    def _session_serial_disconnect(self):
        serial_reader.disconnect()
        self._send_json(200, {"ok": True, "serial_connected": False})

    def _session_readings(self):
        readings = session_state.readings_snapshot()
        latest = readings[-1] if readings else None
        self._send_json(
            200,
            {
                "ok": True,
                "session_id": session_state.session_id,
                "serial_connected": serial_reader.is_connected(),
                "count": len(readings),
                "latest": latest,
                "readings": readings,
            },
        )

    def _session_readings_stream(self, query_string):
        qs = parse_qs(query_string, keep_blank_values=False)
        try:
            last_seq = int(qs.get("last_seq", ["0"])[0])
        except ValueError:
            self._send_json(400, {"ok": False, "error": "invalid_last_seq"})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()

            backlog = serial_reader.frames_after(last_seq)
            for frame in backlog:
                payload = json.dumps(_frame_to_payload(frame), separators=(",", ":"))
                chunk = f"id: {frame.seq}\nevent: reading\ndata: {payload}\n\n".encode("utf-8")
                self.wfile.write(chunk)
                self.wfile.flush()
                last_seq = frame.seq

            while True:
                frames = serial_reader.wait_for_frames_after(last_seq, timeout_s=SSE_HEARTBEAT_SECONDS)
                if not frames:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue

                for frame in frames:
                    payload = json.dumps(_frame_to_payload(frame), separators=(",", ":"))
                    chunk = f"id: {frame.seq}\nevent: reading\ndata: {payload}\n\n".encode("utf-8")
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    last_seq = frame.seq

        except (BrokenPipeError, ConnectionResetError):
            return

    def _session_photos(self):
        self._send_json(200, {"ok": True, "photos": session_state.list_photos()})

    def _session_photo_delete(self, photo_id: str):
        photos = session_state.list_photos()
        photo_rec = next((p for p in photos if p["id"] == photo_id), None)
        removed = session_state.remove_photo(photo_id)
        if removed:
            if photo_rec:
                try:
                    file_path = Path(photo_rec["path"])
                    if file_path.exists():
                        file_path.unlink()
                except OSError:
                    pass
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"ok": False, "error": "photo_not_found"})

    def _session_camera_preview(self):
        _ensure_camera_preview_worker()
        frame, frame_time, start_error = _camera_preview_worker.latest_frame()
        if frame is not None:
            self._send_jpeg(frame)
            return

        # Fallback: if the worker has not delivered a frame yet, try a one-shot still capture.
        preview_id = _uuid.uuid4().hex
        camera_bins = [candidate for candidate in ("rpicam-still", "libcamera-still") if shutil.which(candidate)]
        if not camera_bins:
            self._send_json(503, {"ok": False, "error": "camera_not_available",
                                  "detail": start_error or "rpicam-still / libcamera-still not found"})
            return

        tmp_preview_path = Path(tempfile.gettempdir()) / f"preview-{preview_id}.jpg"
        try:
            if tmp_preview_path.exists():
                tmp_preview_path.unlink()
        except OSError:
            pass

        result = None
        stderr_text = ""
        stdout_text = ""
        timeout_hit = False
        for camera_bin in camera_bins:
            try:
                result = subprocess.run(
                    [
                        camera_bin,
                        "-n",
                        "--immediate",
                        "--nopreview",
                        "--width",
                        "960",
                        "--height",
                        "540",
                        "-o",
                        str(tmp_preview_path),
                    ],
                    capture_output=True,
                    timeout=10,
                )
            except subprocess.TimeoutExpired:
                timeout_hit = True
                continue
            except Exception as exc:
                stderr_text = str(exc)
                continue

            stderr_text = getattr(result, "stderr", b"")
            stdout_text = getattr(result, "stdout", b"")
            if isinstance(stderr_text, bytes):
                stderr_text = stderr_text.decode(errors="replace")
            if isinstance(stdout_text, bytes):
                stdout_text = stdout_text.decode(errors="replace")

            if tmp_preview_path.exists():
                break

        try:
            if tmp_preview_path.exists():
                self._send_jpeg(tmp_preview_path.read_bytes())
                return
            if timeout_hit and not stderr_text and not stdout_text:
                self._send_json(504, {"ok": False, "error": "camera_timeout"})
                return
            self._send_json(502, {"ok": False, "error": "preview_failed", "detail": stderr_text or stdout_text})
        finally:
            try:
                if tmp_preview_path.exists():
                    tmp_preview_path.unlink()
            except OSError:
                pass

    def _session_capture(self):
        photo_id = _uuid.uuid4().hex
        photos_dir = PROJECT_ROOT / "data" / "sessions" / session_state.session_id / "photos"
        photos_dir.mkdir(parents=True, exist_ok=True)
        path = str(photos_dir / f"{photo_id}.jpg")

        _ensure_camera_preview_worker()
        preview_frame, _, _ = _camera_preview_worker.latest_frame()
        if preview_frame is not None:
            try:
                Path(path).write_bytes(preview_frame)
                dimensions: tuple[int, int] | None = None
                thumb_b64 = ""
                try:
                    from PIL import Image
                    img = Image.open(io.BytesIO(preview_frame))
                    dimensions = (img.width, img.height)
                    img.thumbnail((320, 180))
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=70)
                    thumb_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
                except Exception:
                    pass

                photo = session_state.add_photo(path, dimensions=dimensions)
                payload = {"ok": True, "photo": photo, "thumbnail_b64": thumb_b64}
                self._send_json(201, payload)
                return
            except Exception as exc:
                self._send_json(502, {"ok": False, "error": "capture_failed", "detail": str(exc)})
                return

        camera_bins = [candidate for candidate in ("rpicam-still", "libcamera-still") if shutil.which(candidate)]

        if not camera_bins:
            self._send_json(503, {"ok": False, "error": "camera_not_available",
                                   "detail": "rpicam-still / libcamera-still not found"})
            return

        result = None
        stderr_text = ""
        stdout_text = ""
        timeout_hit = False
        output_path = Path(path)
        tmp_capture_path = Path(tempfile.gettempdir()) / f"capture-{photo_id}.jpg"
        try:
            if tmp_capture_path.exists():
                tmp_capture_path.unlink()
        except OSError:
            pass

        for camera_bin in camera_bins:
            try:
                result = subprocess.run(
                    [
                        camera_bin,
                        "-n",
                        "--immediate",
                        "--nopreview",
                        "--width",
                        "1280",
                        "--height",
                        "720",
                        "-o",
                        str(tmp_capture_path),
                    ],
                    capture_output=True, timeout=15,
                )
            except subprocess.TimeoutExpired:
                timeout_hit = True
                continue
            except Exception as exc:
                stderr_text = str(exc)
                continue

            stderr_text = getattr(result, "stderr", b"")
            stdout_text = getattr(result, "stdout", b"")
            if isinstance(stderr_text, bytes):
                stderr_text = stderr_text.decode(errors="replace")
            if isinstance(stdout_text, bytes):
                stdout_text = stdout_text.decode(errors="replace")

            if tmp_capture_path.exists():
                break

        if not tmp_capture_path.exists():
            if timeout_hit and not stderr_text and not stdout_text:
                self._send_json(504, {"ok": False, "error": "camera_timeout"})
                return
            self._send_json(502, {
                "ok": False,
                "error": "capture_failed",
                "detail": stderr_text or stdout_text,
            })
            return

        try:
            shutil.move(str(tmp_capture_path), str(output_path))
        except Exception as exc:
            self._send_json(502, {
                "ok": False,
                "error": "capture_failed",
                "detail": f"captured temp image but failed moving to session path: {exc}",
            })
            return

        dimensions: tuple[int, int] | None = None
        thumb_b64 = ""
        try:
            from PIL import Image
            img = Image.open(path)
            dimensions = (img.width, img.height)
            img.thumbnail((320, 180))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            thumb_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            pass

        photo = session_state.add_photo(path, dimensions=dimensions)
        payload = {"ok": True, "photo": photo, "thumbnail_b64": thumb_b64}
        if result is not None and result.returncode != 0:
            payload["capture_warning"] = {
                "code": result.returncode,
                "detail": stderr_text or "camera exited non-zero after writing image",
            }
        self._send_json(201, payload)

    def _session_analyze(self):
        t0 = time.time()

        try:
            body = self._read_json_body()
        except Exception:
            import traceback as _tb; _tb.print_exc()
            body = {}

        min_readings = max(1, int(body.get("min_readings", 5)))
        readings = session_state.readings_snapshot()
        photos = session_state.list_photos()

        if not photos:
            self._send_json(422, {"ok": False, "error": "validation_failed",
                                   "detail": "at least 1 photo required"})
            return

        if len(readings) < min_readings:
            self._send_json(422, {"ok": False, "error": "validation_failed",
                                   "detail": f"at least {min_readings} readings required; have {len(readings)}"})
            return

        cycle_id = f"lab-{_uuid.uuid4().hex[:12]}"
        from ai.runtime import load_ai_config

        ai_config = load_ai_config(PROJECT_ROOT)
        provider = _get_ai_provider()
        svc = _get_specialist_service()
        initial_ai_runtime = _analysis_runtime_meta(svc)

        def _local_vision_fn() -> dict:
            try:
                raw = _best_vision_result(photos, cycle_id)
                if raw is None:
                    return _no_vision_payload(cycle_id)
                return _build_vision_payload(raw, cycle_id)
            except Exception as exc:
                vp = _no_vision_payload(cycle_id)
                vp["fallback_reason"] = f"pipeline_init_error:{type(exc).__name__}"
                return vp

        tv0 = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            vf = pool.submit(_local_vision_fn)
            ts0 = time.time()
            local_sensor_payload = _build_sensor_payload(readings, cycle_id)
            timing_sensor_ms = (time.time() - ts0) * 1000
            local_vision_payload = vf.result()
        timing_vision_ms = (time.time() - tv0) * 1000

        sensor_payload = dict(local_sensor_payload)
        vision_payload = dict(local_vision_payload)
        ai_specialists_used = False

        try:
            tf0 = time.time()
            fs = _get_fusion_service()
            fused = fs.fuse(cycle_id=cycle_id, sensor_payload=sensor_payload, vision_payload=vision_payload)
            tf1 = time.time()
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": "fusion_failed", "detail": str(exc)})
            return

        if svc is not None:
            ai_specialists_used = True

            def _sensor_fn() -> dict:
                return svc.run_sensor(
                    cycle_id=cycle_id,
                    sensor_input={
                        "rp_ohm": local_sensor_payload.get("rp_ohm", 0.0),
                        "current_ma": local_sensor_payload.get("current_ma", 0.0),
                        "status_band": local_sensor_payload.get("status_band", "UNKNOWN"),
                        "electrochemical_severity_0_to_10": local_sensor_payload.get("electrochemical_severity_0_to_10", 5.0),
                        "confidence_0_to_1": local_sensor_payload.get("confidence_0_to_1", 0.2),
                    },
                )

            def _vision_fn() -> dict:
                ai_vision_input = _ai_vision_payload_from_photos(photos, cycle_id, provider, timeout_seconds=ai_config.sensor_timeout_seconds)
                if ai_vision_input.get("fallback_reason") == "no_photos":
                    return ai_vision_input
                return svc.run_vision(
                    cycle_id=cycle_id,
                    vision_input={
                        "visual_severity_0_to_10": ai_vision_input.get("visual_severity_0_to_10", 5.0),
                        "confidence_0_to_1": ai_vision_input.get("confidence_0_to_1", 0.3),
                        "rust_coverage_band": ai_vision_input.get("rust_coverage_band", "unknown"),
                        "morphology_class": ai_vision_input.get("morphology_class", "unknown"),
                        "surface_summary": ai_vision_input.get("surface_summary", ""),
                        "pit_suspected": ai_vision_input.get("pit_suspected", False),
                        "pit_evidence": ai_vision_input.get("pit_evidence", "not_assessed"),
                        "suspected_damage_modes": ai_vision_input.get("suspected_damage_modes", ["unknown"]),
                        "key_findings": ai_vision_input.get("key_findings", ["no_valid_visual_signal"]),
                        "recommended_actions": ai_vision_input.get("recommended_actions", []),
                        "source_ids": ai_vision_input.get("source_ids", []),
                        "uncertainty_drivers": ai_vision_input.get("uncertainty_drivers", []),
                        "quality_flags": ai_vision_input.get("quality_flags", []),
                    },
                )

            t_spec = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                sf = pool.submit(_sensor_fn)
                vf = pool.submit(_vision_fn)
                try:
                    sensor_payload = sf.result(timeout=max(ai_config.sensor_timeout_seconds, 1.0) + 2.0)
                except (concurrent.futures.TimeoutError, TimeoutError):
                    sf.cancel()
                    sensor_payload = _mark_payload_degraded(local_sensor_payload, "sensor_specialist_timeout")
                try:
                    vision_payload = vf.result(timeout=max(ai_config.vision_timeout_seconds, 1.0) + 2.0)
                except (concurrent.futures.TimeoutError, TimeoutError):
                    vf.cancel()
                    vision_payload = _mark_payload_degraded(local_vision_payload, "vision_specialist_timeout")
            timing_sensor_ms = max(timing_sensor_ms, (time.time() - t_spec) * 1000)
            timing_vision_ms = max(timing_vision_ms, (time.time() - t_spec) * 1000)

            try:
                tf0 = time.time()
                fused = fs.fuse(cycle_id=cycle_id, sensor_payload=sensor_payload, vision_payload=vision_payload)
                tf1 = time.time()
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": "fusion_failed", "detail": str(exc)})
                return

            svc._latest_runtime_payloads = {"sensor": sensor_payload, "vision": vision_payload}

        input_counts = {"photos": len(photos), "readings": len(readings)}
        ai_runtime = _analysis_runtime_meta(svc)
        report = _build_analysis_report(
            sensor_payload=sensor_payload,
            vision_payload=vision_payload,
            fused_payload=fused,
            input_counts=input_counts,
            ai_runtime=ai_runtime,
        )
        if svc is not None and ai_config.enable_cloud_orchestrator:
            try:
                def _final_report_fn() -> dict:
                    return svc.run_final_interpretation(
                        cycle_id=cycle_id,
                        orchestrator_input={
                            "sensor": sensor_payload,
                            "vision": vision_payload,
                            "fused": fused,
                            "input_counts": input_counts,
                            "ai_runtime": initial_ai_runtime,
                        },
                    )

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    ff = pool.submit(_final_report_fn)
                    ai_report = ff.result(timeout=max(ai_config.final_report_timeout_seconds, 1.0) + 1.0)

                svc._latest_runtime_payloads = {"sensor": sensor_payload, "vision": vision_payload, "final": ai_report}
                ai_runtime = _analysis_runtime_meta(svc)
                report = _build_analysis_report(
                    sensor_payload=sensor_payload,
                    vision_payload=vision_payload,
                    fused_payload=fused,
                    input_counts=input_counts,
                    ai_runtime=ai_runtime,
                )

                report = {
                    "headline": ai_report.get("headline", report.get("headline", "")),
                    "overview": ai_report.get("executive_summary", report.get("overview", "")),
                    "conclusion": (
                        f"Overall condition: {ai_report.get('overall_condition', 'unknown')}. "
                        f"Integrated confidence: {int(round(float(ai_report.get('confidence_0_to_1', 0.0)) * 100))}%."
                    ),
                    "sections": [
                        {"title": "Electrochemical Interpretation", "items": ai_report.get("electrochemical_assessment", [])},
                        {"title": "Surface Correlation", "items": ai_report.get("vision_assessment", [])},
                        {"title": "Integrated Interpretation", "items": ai_report.get("cross_modal_assessment", [])},
                        {"title": "Limitations", "items": ai_report.get("limitations", [])},
                        {"title": "Recommended Next Actions", "items": ai_report.get("recommendations", [])},
                    ],
                    "source_ids": ai_report.get("source_ids", []),
                    "sources": _expand_sources(ai_report.get("source_ids", [])),
                    "ai_detailed_report": ai_report,
                }
            except Exception:
                pass

        t_end = time.time()

        self._send_json(200, {
            "ok": True,
            "session_id": session_state.session_id,
            "cycle_id": cycle_id,
            "input_counts": input_counts,
            "ai_specialists_used": ai_specialists_used,
            "ai_runtime": ai_runtime,
            "sensor": sensor_payload,
            "vision": vision_payload,
            "fused": fused,
            "report": report,
            "timing": {
                "total_ms": round((t_end - t0) * 1000, 1),
                "sensor_ms": round(timing_sensor_ms, 1),
                "vision_ms": round(timing_vision_ms, 1),
                "fusion_ms": round((tf1 - tf0) * 1000, 1),
            },
        })

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    with ThreadingReuseTCPServer(("", PORT), DashboardServerHandler) as httpd:
        print(f"Serving beautiful UI on http://localhost:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            serial_reader.disconnect()
