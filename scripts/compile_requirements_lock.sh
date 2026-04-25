#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REQUIRED_PIP_COMPILE_VERSION="7.5.3"

if ! command -v pip-compile >/dev/null 2>&1; then
  echo "[FAIL] pip-compile not found. Install with: python3 -m pip install pip-tools==${REQUIRED_PIP_COMPILE_VERSION}"
  exit 1
fi

PIP_COMPILE_VERSION="$(pip-compile --version | awk '{print $3}')"
if [[ "$PIP_COMPILE_VERSION" != "$REQUIRED_PIP_COMPILE_VERSION" ]]; then
  echo "[FAIL] pip-compile version ${PIP_COMPILE_VERSION} detected."
  echo "       Install required version: python3 -m pip install pip-tools==${REQUIRED_PIP_COMPILE_VERSION}"
  exit 1
fi

export CUSTOM_COMPILE_COMMAND="bash scripts/compile_requirements_lock.sh"

pip-compile \
  --resolver=backtracking \
  --generate-hashes \
  --allow-unsafe \
  --output-file=requirements.lock \
  requirements.in

echo "[PASS] requirements.lock regenerated with pinned transitive dependencies and hashes"
