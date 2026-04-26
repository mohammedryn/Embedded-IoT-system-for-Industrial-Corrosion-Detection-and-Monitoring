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
_specialist_init_attempted = False
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


class _GeminiModelClient:
    """Wraps google.generativeai to satisfy the fusion.specialists.ModelClient protocol."""

    def generate(self, *, model_id: str, prompt: str, timeout_seconds: float) -> str:
        import google.generativeai as genai
        model = genai.GenerativeModel(model_id)
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        fut = ex.submit(lambda: model.generate_content(prompt).text)
        try:
            return fut.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise TimeoutError(f"Gemini {model_id} exceeded {timeout_seconds}s")
        finally:
            # Do not wait for a stuck model call thread; the request path already timed out.
            ex.shutdown(wait=False, cancel_futures=True)


def _get_specialist_service():
    """Return a SpecialistService wired to Gemini if GOOGLE_API_KEY is set, else None."""
    global _specialist_init_attempted, _specialist_service, _specialist_init_error
    if not _specialist_init_attempted:
        with _svc_lock:
            if not _specialist_init_attempted:
                _specialist_init_attempted = True
                if os.environ.get("GOOGLE_API_KEY"):
                    try:
                        from fusion.specialists import SpecialistService, load_ai_settings
                        _specialist_service = SpecialistService(
                            project_root=PROJECT_ROOT,
                            client=_GeminiModelClient(),
                            settings=load_ai_settings(PROJECT_ROOT),
                        )
                        _specialist_init_error = ""
                    except Exception as exc:
                        _specialist_init_error = f"init_failed:{type(exc).__name__}"
                else:
                    _specialist_init_error = "api_key_missing"
    return _specialist_service


def _analysis_runtime_meta(svc) -> dict:
    api_key_present = bool(os.environ.get("GOOGLE_API_KEY"))
    if svc is not None:
        return {
            "mode": "gemini_specialists",
            "api_key_present": api_key_present,
            "specialists_ready": True,
            "message": "Gemini specialists enabled",
        }

    if not api_key_present:
        message = "GOOGLE_API_KEY missing; using local heuristic mode"
    elif _specialist_init_error:
        message = f"Gemini unavailable ({_specialist_init_error}); using local heuristic mode"
    else:
        message = "Gemini unavailable; using local heuristic mode"

    return {
        "mode": "local_heuristic",
        "api_key_present": api_key_present,
        "specialists_ready": False,
        "message": message,
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
        "key_findings": [
            f"mean_rp={round(mean_rp, 1)}_ohm",
            f"n={count}_readings",
            f"status={last_status}",
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
        "key_findings": vision_result.get("key_findings", ["local_hsv_analysis"]),
        "uncertainty_drivers": vision_result.get("uncertainty_drivers", ["local_only"]),
        "quality_flags": vision_result.get("quality_flags", []),
        "degraded_mode": vision_result.get("degraded_mode", False),
        "stale": False,
        "fallback_reason": vision_result.get("fallback_reason", ""),
        "model_id": "vision-local-hsv-v1",
        "schema_version": "c05-vision-v1",
    }


def _no_vision_payload(cycle_id: str) -> dict:
    from datetime import datetime, timezone
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "visual_severity_0_to_10": 5.0, "confidence_0_to_1": 0.1,
        "rust_coverage_band": "unknown", "morphology_class": "unknown",
        "key_findings": ["no_photos_captured"],
        "uncertainty_drivers": ["no_images"],
        "quality_flags": ["no_photos"],
        "degraded_mode": True, "stale": False,
        "fallback_reason": "no_photos",
        "model_id": "heuristic-v1", "schema_version": "c05-vision-v1",
    }


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
        self.wfile.write(body)

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
        svc = _get_specialist_service()
        ai_runtime = _analysis_runtime_meta(svc)
        specialist_timeout_seconds = 30.0

        if svc is not None:
            # AI specialist path: sensor and vision both route through Gemini concurrently.
            rp_values = [r["rp_ohm"] for r in readings if r.get("rp_ohm", 0) > 0]
            mean_rp = sum(rp_values) / len(rp_values) if rp_values else 0.0
            current_values = [r.get("current_ua", 0.0) for r in readings]
            mean_current_ma = (sum(current_values) / len(current_values) / 1000.0) if current_values else 0.0
            last_status = readings[-1].get("status", "UNKNOWN").upper() if readings else "UNKNOWN"

            def _sensor_fn() -> dict:
                return svc.run_sensor(
                    cycle_id=cycle_id,
                    sensor_input={
                        "rp_ohm": mean_rp,
                        "current_ma": mean_current_ma,
                        "status_band": last_status,
                    },
                )

            def _vision_fn() -> dict:
                try:
                    raw = _best_vision_result(photos, cycle_id)
                    if raw is None:
                        return _no_vision_payload(cycle_id)
                    return svc.run_vision(
                        cycle_id=cycle_id,
                        vision_input={
                            "visual_severity_0_to_10": raw.get("visual_severity_0_to_10", 5.0),
                            "confidence_0_to_1": raw.get("confidence_0_to_1", 0.3),
                            "rust_coverage_band": raw.get("rust_coverage_band", "unknown"),
                            "morphology_class": raw.get("morphology_class", "unknown"),
                        },
                    )
                except Exception as exc:
                    vp = _no_vision_payload(cycle_id)
                    vp["fallback_reason"] = f"pipeline_init_error:{type(exc).__name__}"
                    return vp

            t_spec = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                sf = pool.submit(_sensor_fn)
                vf = pool.submit(_vision_fn)
                try:
                    sensor_payload = sf.result(timeout=specialist_timeout_seconds)
                    ts1 = time.time()
                    vision_payload = vf.result(timeout=specialist_timeout_seconds)
                    tv1 = time.time()
                except concurrent.futures.TimeoutError:
                    sf.cancel()
                    vf.cancel()
                    self._send_json(504, {
                        "ok": False,
                        "error": "analysis_timeout",
                        "detail": f"AI specialist call exceeded {int(specialist_timeout_seconds)}s",
                    })
                    return
            timing_sensor_ms = (ts1 - t_spec) * 1000
            timing_vision_ms = (tv1 - t_spec) * 1000
        else:
            # Heuristic path: vision runs in background, sensor heuristic on main thread.
            def _vision_fn() -> dict:
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
                vf = pool.submit(_vision_fn)
                ts0 = time.time()
                sensor_payload = _build_sensor_payload(readings, cycle_id)
                timing_sensor_ms = (time.time() - ts0) * 1000
                vision_payload = vf.result()
            timing_vision_ms = (time.time() - tv0) * 1000

        try:
            tf0 = time.time()
            fs = _get_fusion_service()
            fused = fs.fuse(cycle_id=cycle_id, sensor_payload=sensor_payload, vision_payload=vision_payload)
            tf1 = time.time()
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": "fusion_failed", "detail": str(exc)})
            return

        t_end = time.time()

        self._send_json(200, {
            "ok": True,
            "session_id": session_state.session_id,
            "cycle_id": cycle_id,
            "input_counts": {"photos": len(photos), "readings": len(readings)},
            "ai_specialists_used": svc is not None,
            "ai_runtime": ai_runtime,
            "sensor": sensor_payload,
            "vision": vision_payload,
            "fused": fused,
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