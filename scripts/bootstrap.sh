#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip==25.0.1
pip install --require-hashes -r requirements.lock

echo "Bootstrap complete. Activate with: source .venv/bin/activate"
