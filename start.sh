#!/usr/bin/env bash
# Run this once after boot:  bash start.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL="http://127.0.0.1:8080"

cd "$REPO"
source .venv/bin/activate

# --- start server in background (logs stay visible in this terminal) ---
python3 -m edge.web_server &
SERVER_PID=$!
echo "Server starting (pid $SERVER_PID) ..."

# --- wait up to 30 s for the server to accept requests ---
for i in $(seq 1 30); do
    if curl -sf "$URL/api/state" >/dev/null 2>&1; then
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "Server process died unexpectedly." >&2
        exit 1
    fi
    sleep 1
done

if ! curl -sf "$URL/api/state" >/dev/null 2>&1; then
    echo "Server did not become ready in 30 s." >&2
    kill "$SERVER_PID" 2>/dev/null || true
    exit 1
fi

# --- new session ---
SESSION=$(curl -sS -X POST "$URL/api/session/new")
SESSION_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['session_id'])" "$SESSION")
echo "Session: $SESSION_ID"

# --- auto-connect serial if a controller is plugged in ---
SERIAL_PORT=""
for candidate in /dev/ttyACM* /dev/ttyUSB*; do
    if [[ -e "$candidate" ]]; then
        SERIAL_PORT="$candidate"
        break
    fi
done

if [[ -n "$SERIAL_PORT" ]]; then
    curl -sS -X POST "$URL/api/session/serial/connect" \
        -H "Content-Type: application/json" \
        -d "{\"port\":\"$SERIAL_PORT\",\"baud\":115200}" >/dev/null
    echo "Serial connected: $SERIAL_PORT"
else
    echo "No serial device found - connect manually via the dashboard."
fi

echo ""
echo "Dashboard -> $URL"
echo "Press Ctrl+C to stop the server."
echo ""

# --- keep server running in the foreground ---
wait "$SERVER_PID"
