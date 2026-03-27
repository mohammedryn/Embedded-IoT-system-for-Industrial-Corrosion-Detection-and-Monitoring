#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

if [[ ! -d .venv ]]; then
  echo "[FAIL] .venv missing. Run: make bootstrap"
  exit 1
fi

source .venv/bin/activate
python scripts/check_config_override.py | tee /tmp/c00_cfg.out
python scripts/log_sample.py

if ! grep -q "runtime.cycle_seconds=12" /tmp/c00_cfg.out; then
  echo "[FAIL] env override check failed"
  exit 1
fi

if [[ ! -f data/logs/edge.log ]]; then
  echo "[FAIL] structured log file not found"
  exit 1
fi

if ! tail -n 5 data/logs/edge.log | grep -q '"event": "c00_log_smoke"'; then
  echo "[FAIL] structured log event not found"
  exit 1
fi

echo "[PASS] C00 smoke checks passed"
