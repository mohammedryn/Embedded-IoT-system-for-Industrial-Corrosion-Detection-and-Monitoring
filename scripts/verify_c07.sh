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
python scripts/verify_c07.py

if [[ ! -f data/sessions/c07/c07-verification-summary.json ]]; then
  echo "[FAIL] missing C07 summary artifact"
  exit 1
fi

if ! grep -q '"status": "pass"' data/sessions/c07/c07-verification-summary.json; then
  echo "[FAIL] C07 verification failed"
  exit 1
fi

echo "[PASS] C07 smoke checks passed"
