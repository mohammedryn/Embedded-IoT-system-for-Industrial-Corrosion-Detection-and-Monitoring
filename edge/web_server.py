#!/usr/bin/env python3
import http.server
import socketserver
import json
import os
import mimetypes
from pathlib import Path

PORT = 8080

# Paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "web"
SESSION_DIR = PROJECT_ROOT / "data" / "sessions" / "c07"
DASHBOARD_JSON = SESSION_DIR / "dashboard-latest.json"

class DashboardServerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/state":
            self._serve_state()
        else:
            # Fall back to serving static files from WEB_DIR
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/control":
            self._handle_control()
        else:
            self.send_error(404, "Not Found")

    def _serve_state(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        
        if DASHBOARD_JSON.exists():
            payload = DASHBOARD_JSON.read_bytes()
            self.wfile.write(payload)
        else:
            # Send default mock data if not generated yet
            mock = {
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
                "phase_markers": ["baseline", "acceleration", "active", "severe", "fresh_swap"]
            }
            self.wfile.write(json.dumps(mock).encode('utf-8'))

    def _handle_control(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        
        try:
            req = json.loads(post_data.decode('utf-8'))
            action = req.get("action")
            
            # Since C07 orchestration is currently a static invocation in verify script,
            # this backend serves as a mock receiver. A real daemon would connect here.
            print(f">>> UI Control Received: {action}")
            
            self.wfile.write(json.dumps({"status": "ok", "action": action}).encode('utf-8'))
        except Exception as e:
            self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

    # Suppress verbose default logging
    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), DashboardServerHandler) as httpd:
        print(f"Serving beautiful UI on http://localhost:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
