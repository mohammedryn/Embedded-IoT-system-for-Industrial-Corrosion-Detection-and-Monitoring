#!/usr/bin/env python3
import json
import http.server
import socketserver
import time
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

        super().do_GET()

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