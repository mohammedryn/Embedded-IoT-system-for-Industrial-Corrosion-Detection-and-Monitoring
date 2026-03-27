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
python scripts/verify_c06.py

if [[ ! -f data/sessions/c06/c06-verification-summary.json ]]; then
  echo "[FAIL] missing C06 summary artifact"
  exit 1
fi

if ! grep -q '"status": "pass"' data/sessions/c06/c06-verification-summary.json; then
  echo "[FAIL] C06 verification failed"
  exit 1
fi

echo "[PASS] C06 smoke checks passed"