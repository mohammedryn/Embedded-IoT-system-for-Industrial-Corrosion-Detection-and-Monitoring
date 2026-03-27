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
python scripts/c04_make_synthetic_images.py
python scripts/verify_c04.py

if [[ ! -f data/sessions/c04/c04-verification-summary.json ]]; then
  echo "[FAIL] missing C04 summary artifact"
  exit 1
fi

if ! grep -q '"status": "pass"' data/sessions/c04/c04-verification-summary.json; then
  echo "[FAIL] C04 verification failed"
  exit 1
fi

echo "[PASS] C04 smoke checks passed"
