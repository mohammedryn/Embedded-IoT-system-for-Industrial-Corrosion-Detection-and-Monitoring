#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

HOST="${LAB_HOST:-127.0.0.1}"
PORT="${LAB_PORT:-8080}"
BAUD="${LAB_BAUD:-115200}"
SERIAL_PORT="${LAB_SERIAL_PORT:-}"
LOG_DIR="$ROOT_DIR/data/logs"
SERVER_LOG="$LOG_DIR/lab-session-server.log"
SERVER_PID_FILE="$LOG_DIR/lab-session-server.pid"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/start_lab_session.sh

Optional environment variables:
  LAB_SERIAL_PORT=/dev/ttyACM0   Force a specific serial device
  LAB_BAUD=115200                Serial baud (default 115200)
  LAB_HOST=127.0.0.1             Server host (default 127.0.0.1)
  LAB_PORT=8080                  Server port (default 8080)
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[FAIL] required command not found: $cmd"
    exit 1
  fi
}

server_ready() {
  curl -fsS "http://${HOST}:${PORT}/api/state" >/dev/null 2>&1
}

detect_serial_port() {
  if [[ -n "$SERIAL_PORT" ]]; then
    printf '%s\n' "$SERIAL_PORT"
    return 0
  fi

  local candidate
  for candidate in /dev/ttyACM* /dev/ttyUSB*; do
    if [[ -e "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

extract_json_field() {
  local payload="$1"
  local field="$2"
  python3 -c 'import json,sys; data=json.loads(sys.argv[1]); value=data
for part in sys.argv[2].split("."):
    value=value[part]
print(value)' "$payload" "$field"
}

start_server_if_needed() {
  mkdir -p "$LOG_DIR"

  if server_ready; then
    echo "[INFO] server already running on http://${HOST}:${PORT}"
    return 0
  fi

  echo "[INFO] starting edge.web_server ..."
  nohup python3 -m edge.web_server >"$SERVER_LOG" 2>&1 &
  local pid=$!
  echo "$pid" >"$SERVER_PID_FILE"

  local attempt
  for attempt in $(seq 1 30); do
    if server_ready; then
      echo "[OK] server started (pid $pid)"
      return 0
    fi
    sleep 1
  done

  echo "[FAIL] server did not become ready within 30 seconds"
  echo "[INFO] recent server log:"
  tail -n 40 "$SERVER_LOG" || true
  exit 1
}

main() {
  if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
  fi

  require_cmd curl
  require_cmd python3

  if [[ ! -d .venv ]]; then
    echo "[FAIL] .venv missing. Run: make bootstrap"
    exit 1
  fi

  # shellcheck disable=SC1091
  source .venv/bin/activate

  start_server_if_needed

  echo "[INFO] creating fresh lab session ..."
  local session_response
  session_response="$(curl -fsS -X POST "http://${HOST}:${PORT}/api/session/new")"
  local session_id
  session_id="$(extract_json_field "$session_response" "session_id")"
  echo "[OK] session created: ${session_id}"

  local connect_message="[INFO] serial connect skipped"
  local serial_response=""
  if SERIAL_PORT="$(detect_serial_port)"; then
    echo "[INFO] detected serial device: ${SERIAL_PORT}"
    curl -fsS -X POST "http://${HOST}:${PORT}/api/session/serial/disconnect" >/dev/null || true
    if serial_response="$(curl -fsS -X POST "http://${HOST}:${PORT}/api/session/serial/connect" \
      -H 'Content-Type: application/json' \
      -d "{\"port\":\"${SERIAL_PORT}\",\"baud\":${BAUD}}")"; then
      if [[ "$(extract_json_field "$serial_response" "ok")" == "True" || "$(extract_json_field "$serial_response" "ok")" == "true" ]]; then
        connect_message="[OK] serial connected: ${SERIAL_PORT} @ ${BAUD}"
      else
        connect_message="[WARN] serial connection request returned a non-ok response"
      fi
    else
      connect_message="[WARN] failed to connect serial device ${SERIAL_PORT}"
    fi
  else
    connect_message="[WARN] no /dev/ttyACM* or /dev/ttyUSB* device found; continuing without serial"
  fi

  echo "$connect_message"
  echo
  echo "Lab session is ready."
  echo "Open this in the Pi browser:"
  echo "  http://localhost:${PORT}"
  echo
  echo "Useful status files:"
  echo "  server log: ${SERVER_LOG}"
  echo "  server pid: ${SERVER_PID_FILE}"
  echo
  echo "Quick API checks:"
  echo "  curl -sS http://${HOST}:${PORT}/api/session/readings | jq ."
  echo "  curl -N -H 'Accept: text/event-stream' 'http://${HOST}:${PORT}/api/session/readings/stream?last_seq=0'"
}

main "$@"
