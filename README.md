# Corrosion Monitoring Project

This repository follows chunk-wise execution from C00 onward.

## Quick Start (C00)

1. Run bootstrap:
   - `make bootstrap`
2. If you change dependencies in requirements.in, regenerate the hash-locked file:
   - `python3 -m pip install pip-tools==7.5.3`
   - `make lock`
3. Run C00 smoke checks:
   - `make smoke-c00`
4. Run C01 tooling verification:
   - `make smoke-c01`

## C04, C05, C06, and C07 Verification

1. Run vision smoke checks:
   - `make smoke-c04`
2. Run AI specialist smoke checks:
   - `make smoke-c05`
3. Run fusion and RUL smoke checks:
   - `make smoke-c06`
4. Run UX/demo runtime orchestration checks:
   - `make smoke-c07`

Expected output lines:
- `[PASS] C04 smoke checks passed`
- `[PASS] C05 smoke checks passed`
- `[PASS] C06 smoke checks passed`
- `[PASS] C07 smoke checks passed`

Artifacts:
- `data/sessions/c04/c04-verification-summary.json`
- `data/sessions/c05/c05-verification-summary.json`
- `data/sessions/c06/c06-verification-summary.json`
- `data/sessions/c07/c07-verification-summary.json`

## Lab Session Serial Ingestion

The runtime supports direct Teensy FRAME ingestion and live streaming into the dashboard backend.

### Serial defaults

- device: `/dev/ttyACM0`
- baud: `115200`

### Session API quickstart

1. Create a session:
   - `curl -sS -X POST http://127.0.0.1:8080/api/session/new`
2. Connect serial:
   - `curl -sS -X POST http://127.0.0.1:8080/api/session/serial/connect -H 'Content-Type: application/json' -d '{"port":"/dev/ttyACM0","baud":115200}'`
3. Read current readings snapshot:
   - `curl -sS http://127.0.0.1:8080/api/session/readings`
4. Stream live readings (SSE):
   - `curl -N -H 'Accept: text/event-stream' http://127.0.0.1:8080/api/session/readings/stream`
5. Disconnect serial:
   - `curl -sS -X POST http://127.0.0.1:8080/api/session/serial/disconnect`

### Linux troubleshooting

- If `/dev/ttyACM0` permission is denied:
  - `sudo usermod -aG dialout "$USER"`
  - Log out and back in to refresh group membership.
- Check dialout membership:
  - `id -nG | tr ' ' '\n' | grep -x dialout`
- Find serial port conflicts:
  - `sudo lsof /dev/ttyACM0`


## Lab Session GUI

The dashboard includes a guided 3-step Lab Session workflow accessible via the **Lab Session** tab.

### Steps

1. **Capture** — take one or more surface photos using the Pi camera before immersion.
2. **Measure** — connect the Teensy serial port and collect live Rp readings until the target count is met.
3. **Analyze** — run vision + electrochemical fusion and view the fused result card (severity, RUL, confidence).

### Lab Session quickstart

```bash
# 1. Start the server
python3 -m edge.web_server

# 2. Navigate to http://127.0.0.1:8080 in your browser
#    Linux:  xdg-open http://127.0.0.1:8080
#    macOS:  open http://127.0.0.1:8080

# 3. Click "Lab Session" tab and follow the stepper
```

### Lab Session API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/session/new` | Reset session state (photos + readings cleared) |
| `POST` | `/api/session/capture` | Capture a photo via rpicam-still or libcamera-still |
| `GET` | `/api/session/photos` | List session photos |
| `DELETE` | `/api/session/photos/<id>` | Remove a photo (also deletes file on disk) |
| `POST` | `/api/session/analyze` | Run sensor + vision + fusion analysis |
| `POST` | `/api/session/serial/connect` | Connect the Teensy serial port |
| `POST` | `/api/session/serial/disconnect` | Disconnect serial |
| `GET` | `/api/session/readings` | Snapshot of collected readings |
| `GET` | `/api/session/readings/stream` | SSE stream of live frames |

### Example curl calls

```bash
# New session
curl -sS -X POST http://127.0.0.1:8080/api/session/new | jq .

# Capture a photo
curl -sS -X POST http://127.0.0.1:8080/api/session/capture | jq .

# List photos
curl -sS http://127.0.0.1:8080/api/session/photos | jq .

# Delete a photo
curl -sS -X DELETE http://127.0.0.1:8080/api/session/photos/<photo_id> | jq .

# Connect serial
curl -sS -X POST http://127.0.0.1:8080/api/session/serial/connect \
  -H 'Content-Type: application/json' \
  -d '{"port":"/dev/ttyACM0","baud":115200}' | jq .

# Stream readings (SSE)
curl -N -H 'Accept: text/event-stream' \
  'http://127.0.0.1:8080/api/session/readings/stream?last_seq=0'

# Run analysis (with custom min_readings)
curl -sS -X POST http://127.0.0.1:8080/api/session/analyze \
  -H 'Content-Type: application/json' \
  -d '{"min_readings": 10}' | jq .
```

The analyze response includes `session_id`, `input_counts`, `sensor`, `vision`, `fused`, and `timing`.

### Camera dependency

The capture endpoint requires **rpicam-still** (Raspberry Pi OS Bookworm+) or **libcamera-still**
(older Pi OS). The server probes for each in that order and returns HTTP 503 if neither is found.

Install on Pi:
```bash
sudo apt-get install -y rpicam-apps   # Bookworm
# or
sudo apt-get install -y libcamera-apps  # older
```

### Typical failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `503 camera_not_available` | Neither camera binary on PATH | Install `rpicam-apps` / `libcamera-apps` |
| `502 capture_failed` | Camera returns non-zero exit | Check Pi camera ribbon cable; `rpicam-still --list-cameras` |
| `504 camera_timeout` | Capture hung for > 15 s | Kill hanging camera process; check Pi thermal throttling |
| `422 validation_failed – photo` | Analyze called with 0 photos | Capture at least 1 photo before analyzing |
| `422 validation_failed – readings` | Fewer readings than `min_readings` | Collect more readings or lower target in UI |
| `502 serial_connect_failed` | Serial port not found / permission denied | Check `/dev/ttyACM0` exists; `sudo usermod -aG dialout $USER` |
| `500 fusion_failed` | Fusion service init error | Check `fusion/` imports; inspect server log |

## Top-Level Structure

- firmware: Teensy firmware artifacts
- edge: Raspberry Pi ingestion/orchestration code
- vision: Vision subsystem code and models
- fusion: Fusion logic and policy
- models: ML model assets
- config: versioned YAML configuration
- scripts: setup, checks, utilities
- docs/runbooks: setup, troubleshooting, demo checklist, operations
- tests: automated tests
- data/logs: runtime logs
- data/sessions: captured session artifacts
