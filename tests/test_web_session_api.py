import http.client
import json
import threading
from pathlib import Path

import pytest

import edge.web_server as web_server
from edge.serial_reader import SerialFrame


@pytest.fixture()
def running_server(monkeypatch):
    web_server.session_state.new_session()

    server = web_server.ThreadingReuseTCPServer(("127.0.0.1", 0), web_server.DashboardServerHandler)
    host, port = server.server_address

    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    try:
        yield host, port, monkeypatch
    finally:
        server.shutdown()
        server.server_close()


def _request_json(method: str, host: str, port: int, path: str, body: dict | None = None):
    conn = http.client.HTTPConnection(host, port, timeout=2)
    payload = None
    headers = {}
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    return response.status, raw


def test_session_new_endpoint(running_server):
    host, port, _ = running_server
    status, raw = _request_json("POST", host, port, "/api/session/new")
    assert status == 201

    payload = json.loads(raw.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["session_id"]


def test_serial_connect_disconnect_endpoints(running_server):
    host, port, monkeypatch = running_server

    called = {"connect": None, "disconnect": 0}

    def fake_connect(*, port: str, baud: int):
        called["connect"] = (port, baud)

    def fake_disconnect():
        called["disconnect"] += 1

    monkeypatch.setattr(web_server.serial_reader, "connect", fake_connect)
    monkeypatch.setattr(web_server.serial_reader, "disconnect", fake_disconnect)
    monkeypatch.setattr(web_server.serial_reader, "is_connected", lambda: True)

    status, raw = _request_json(
        "POST",
        host,
        port,
        "/api/session/serial/connect",
        {"port": "/dev/ttyACM0", "baud": 115200},
    )
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    assert payload["ok"] is True
    assert called["connect"] == ("/dev/ttyACM0", 115200)

    status, raw = _request_json("POST", host, port, "/api/session/serial/disconnect")
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["serial_connected"] is False
    assert called["disconnect"] == 1


def test_session_readings_snapshot_endpoint(running_server):
    host, port, _ = running_server

    web_server.session_state.add_reading(
        {
            "seq": 1,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "rp_ohm": 9663.52,
            "current_ua": 1.034,
            "status": "FAIR",
        }
    )

    status, raw = _request_json("GET", host, port, "/api/session/readings")
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["count"] >= 1
    assert payload["latest"]["rp_ohm"] == pytest.approx(9663.52)


def test_sse_stream_emits_reading(running_server):
    host, port, monkeypatch = running_server

    frame = SerialFrame(
        seq=3,
        timestamp="2026-01-01T00:00:03+00:00",
        timestamp_unix=1767225603.0,
        rp_ohm=1234.5,
        current_ua=0.42,
        status="FAIR",
        asym_percent=0.1,
        raw="FRAME:Rp:1234.5;I:0.42;status:FAIR;asym:0.1",
    )

    monkeypatch.setattr(web_server.serial_reader, "frames_after", lambda last_seq: [frame])
    monkeypatch.setattr(web_server.serial_reader, "wait_for_frames_after", lambda last_seq, timeout_s: [])

    conn = http.client.HTTPConnection(host, port, timeout=3)
    conn.request("GET", "/api/session/readings/stream")
    response = conn.getresponse()

    assert response.status == 200
    assert response.getheader("Content-Type") == "text/event-stream"

    chunk = response.read(512).decode("utf-8")
    conn.close()

    assert "event: reading" in chunk
    assert '"rp_ohm":1234.5' in chunk


# ─── Photo lifecycle ─────────────────────────────────────────────────────────

def test_session_photos_lifecycle(running_server):
    host, port, _ = running_server
    web_server.session_state.new_session()

    status, raw = _request_json("GET", host, port, "/api/session/photos")
    assert status == 200
    payload = json.loads(raw.decode())
    assert payload["ok"] is True
    assert payload["photos"] == []

    photo = web_server.session_state.add_photo("/tmp/test_photo_lifecycle.jpg")
    photo_id = photo["id"]

    status, raw = _request_json("GET", host, port, "/api/session/photos")
    assert status == 200
    payload = json.loads(raw.decode())
    assert len(payload["photos"]) == 1
    assert payload["photos"][0]["id"] == photo_id

    status, raw = _request_json("DELETE", host, port, f"/api/session/photos/{photo_id}")
    assert status == 200
    assert json.loads(raw.decode())["ok"] is True

    status, raw = _request_json("GET", host, port, "/api/session/photos")
    assert json.loads(raw.decode())["photos"] == []


def test_delete_nonexistent_photo_returns_404(running_server):
    host, port, _ = running_server
    status, raw = _request_json("DELETE", host, port, "/api/session/photos/does-not-exist")
    assert status == 404
    payload = json.loads(raw.decode())
    assert payload["ok"] is False
    assert payload["error"] == "photo_not_found"


# ─── Capture endpoint ─────────────────────────────────────────────────────────

def test_capture_invokes_camera_command(running_server):
    host, port, monkeypatch = running_server
    web_server.session_state.new_session()

    captured_args: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        captured_args.append(cmd)
        Path(cmd[cmd.index("-o") + 1]).touch()

        class _FakeResult:
            returncode = 0
            stderr = b""

        return _FakeResult()

    monkeypatch.setattr(web_server.subprocess, "run", fake_run)
    monkeypatch.setattr(web_server.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name == "rpicam-still" else None)

    status, raw = _request_json("POST", host, port, "/api/session/capture")
    assert status == 201
    payload = json.loads(raw.decode())
    assert payload["ok"] is True
    assert payload["photo"]["id"]
    assert len(captured_args) == 1
    assert captured_args[0][0] == "rpicam-still"
    assert "-o" in captured_args[0]

    status2, raw2 = _request_json("GET", host, port, "/api/session/photos")
    photos = json.loads(raw2.decode())["photos"]
    assert any(p["id"] == payload["photo"]["id"] for p in photos)


def test_capture_falls_back_to_libcamera(running_server):
    host, port, monkeypatch = running_server
    web_server.session_state.new_session()

    captured_bin: list[str] = []

    def fake_run(cmd, **kwargs):
        captured_bin.append(cmd[0])
        Path(cmd[cmd.index("-o") + 1]).touch()

        class _FakeResult:
            returncode = 0
            stderr = b""

        return _FakeResult()

    monkeypatch.setattr(web_server.subprocess, "run", fake_run)
    monkeypatch.setattr(
        web_server.shutil, "which",
        lambda name: f"/usr/bin/{name}" if name == "libcamera-still" else None,
    )

    status, raw = _request_json("POST", host, port, "/api/session/capture")
    assert status == 201
    assert captured_bin[0] == "libcamera-still"


def test_capture_no_camera_returns_503(running_server):
    host, port, monkeypatch = running_server
    monkeypatch.setattr(web_server.shutil, "which", lambda name: None)

    status, raw = _request_json("POST", host, port, "/api/session/capture")
    assert status == 503
    payload = json.loads(raw.decode())
    assert payload["ok"] is False
    assert payload["error"] == "camera_not_available"


def test_capture_camera_nonzero_exit_returns_502(running_server):
    host, port, monkeypatch = running_server
    web_server.session_state.new_session()

    def fake_run(cmd, **kwargs):
        class _FakeResult:
            returncode = 1
            stderr = b"camera error"

        return _FakeResult()

    monkeypatch.setattr(web_server.subprocess, "run", fake_run)
    monkeypatch.setattr(web_server.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name == "rpicam-still" else None)

    status, raw = _request_json("POST", host, port, "/api/session/capture")
    assert status == 502
    payload = json.loads(raw.decode())
    assert payload["ok"] is False
    assert payload["error"] == "capture_failed"


# ─── Analyze endpoint ─────────────────────────────────────────────────────────

def test_analyze_requires_at_least_one_photo(running_server):
    host, port, _ = running_server
    web_server.session_state.new_session()

    for i in range(10):
        web_server.session_state.add_reading(
            {"seq": i, "rp_ohm": 5000.0, "current_ua": 1.0, "status": "FAIR"}
        )

    status, raw = _request_json("POST", host, port, "/api/session/analyze")
    assert status == 422
    payload = json.loads(raw.decode())
    assert payload["ok"] is False
    assert payload["error"] == "validation_failed"
    assert "photo" in payload["detail"]


def test_analyze_requires_minimum_readings(running_server):
    host, port, _ = running_server
    web_server.session_state.new_session()

    web_server.session_state.add_photo("/tmp/test_analyze_prereq.jpg")

    for i in range(3):
        web_server.session_state.add_reading(
            {"seq": i, "rp_ohm": 5000.0, "current_ua": 1.0, "status": "FAIR"}
        )

    status, raw = _request_json("POST", host, port, "/api/session/analyze",
                                body={"min_readings": 5})
    assert status == 422
    payload = json.loads(raw.decode())
    assert payload["ok"] is False
    assert "readings" in payload["detail"]


def test_analyze_success_with_mocked_services(running_server):
    host, port, monkeypatch = running_server
    web_server.session_state.new_session()

    web_server.session_state.add_photo("/tmp/test_analyze_ok.jpg")
    for i in range(5):
        web_server.session_state.add_reading(
            {"seq": i, "rp_ohm": 20000.0, "current_ua": 0.5, "status": "FAIR"}
        )

    fake_vision_result = {
        "visual_severity_0_to_10": 3.0,
        "confidence_0_to_1": 0.7,
        "rust_coverage_band": "low",
        "morphology_class": "uniform",
        "key_findings": ["mock_finding"],
        "uncertainty_drivers": [],
        "quality_flags": [],
        "degraded_mode": False,
        "fallback_reason": "",
    }

    class _FakeVP:
        def analyze_image(self, path, cycle_id):
            return fake_vision_result

    class _FakeFS:
        def fuse(self, **kwargs):
            return {
                "fused_severity_0_to_10": 3.5,
                "rul_days": 200.0,
                "confidence_0_to_1": 0.75,
                "degraded_mode": False,
                "rationale": "mock rationale",
            }

    # Force heuristic path (no Gemini specialist).
    monkeypatch.setattr(web_server, "_get_specialist_service", lambda: None)
    monkeypatch.setattr(web_server, "_vision_pipeline", _FakeVP())
    monkeypatch.setattr(web_server, "_fusion_service", _FakeFS())

    status, raw = _request_json("POST", host, port, "/api/session/analyze",
                                body={"min_readings": 5})
    assert status == 200
    payload = json.loads(raw.decode())
    assert payload["ok"] is True
    assert payload["session_id"]
    assert payload["cycle_id"].startswith("lab-")
    assert payload["input_counts"]["photos"] == 1
    assert payload["input_counts"]["readings"] == 5
    assert payload["ai_specialists_used"] is False
    assert "sensor" in payload
    assert "vision" in payload
    assert "fused" in payload
    assert "timing" in payload
    assert payload["timing"]["total_ms"] >= 0
    assert payload["fused"]["rul_days"] == pytest.approx(200.0)


def test_analyze_uses_specialist_service_when_set(running_server):
    host, port, monkeypatch = running_server
    web_server.session_state.new_session()

    web_server.session_state.add_photo("/tmp/test_specialist_analyze.jpg")
    for i in range(5):
        web_server.session_state.add_reading(
            {"seq": i, "rp_ohm": 20000.0, "current_ua": 0.5, "status": "FAIR"}
        )

    class _FakeVP:
        def analyze_image(self, path, cycle_id):
            return {
                "visual_severity_0_to_10": 3.0, "confidence_0_to_1": 0.70,
                "rust_coverage_band": "light", "morphology_class": "uniform",
                "key_findings": ["hsv_finding"], "uncertainty_drivers": [],
                "quality_flags": [], "degraded_mode": False, "fallback_reason": "",
            }

    class _FakeSVC:
        def run_sensor(self, *, cycle_id, sensor_input):
            return {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "cycle_id": cycle_id, "rp_ohm": sensor_input["rp_ohm"],
                "current_ma": sensor_input["current_ma"],
                "status_band": sensor_input["status_band"],
                "electrochemical_severity_0_to_10": 4.0, "confidence_0_to_1": 0.85,
                "key_findings": ["specialist_sensor_finding"],
                "uncertainty_drivers": ["none"], "quality_flags": [],
                "degraded_mode": False, "stale": False, "fallback_reason": "",
                "model_id": "gemini-3-flash-preview", "schema_version": "c05-sensor-v1",
            }

        def run_vision(self, *, cycle_id, vision_input):
            return {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "cycle_id": cycle_id,
                "visual_severity_0_to_10": 3.5, "confidence_0_to_1": 0.80,
                "rust_coverage_band": "light", "morphology_class": "uniform",
                "key_findings": ["specialist_vision_finding"],
                "uncertainty_drivers": ["none"], "quality_flags": [],
                "degraded_mode": False, "stale": False, "fallback_reason": "",
                "model_id": "gemini-3-flash-preview", "schema_version": "c05-vision-v1",
            }

    class _FakeFS:
        def fuse(self, **kwargs):
            return {"fused_severity_0_to_10": 3.8, "rul_days": 180.0,
                    "confidence_0_to_1": 0.82}

    monkeypatch.setattr(web_server, "_get_specialist_service", lambda: _FakeSVC())
    monkeypatch.setattr(web_server, "_vision_pipeline", _FakeVP())
    monkeypatch.setattr(web_server, "_fusion_service", _FakeFS())

    status, raw = _request_json("POST", host, port, "/api/session/analyze",
                                body={"min_readings": 5})
    assert status == 200
    payload = json.loads(raw.decode())
    assert payload["ok"] is True
    assert payload["ai_specialists_used"] is True
    assert "specialist_sensor_finding" in payload["sensor"]["key_findings"]
    assert "specialist_vision_finding" in payload["vision"]["key_findings"]
    assert payload["sensor"]["model_id"] == "gemini-3-flash-preview"
    assert payload["vision"]["model_id"] == "gemini-3-flash-preview"
    assert payload["fused"]["rul_days"] == pytest.approx(180.0)