import http.client
import json
import threading

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