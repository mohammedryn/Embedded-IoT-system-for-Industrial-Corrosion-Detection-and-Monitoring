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
