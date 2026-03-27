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

python scripts/c01_make_synthetic_data.py
python scripts/c01_signal_validator.py \
  --waveform-csv data/sessions/c01/waveform_synthetic.csv \
  --adc-csv data/sessions/c01/adc_baseline_synthetic.csv \
  --output data/sessions/c01/validation-summary-baseline.json

python scripts/c01_signal_validator.py \
  --adc-csv data/sessions/c01/adc_polarity_synthetic.csv \
  --adc-std-max 0.01 \
  --adc-p2p-max 0.02 \
  --expect-correlation positive \
  --output data/sessions/c01/validation-summary-polarity.json

if [[ ! -f data/sessions/c01/validation-summary-baseline.json ]]; then
  echo "[FAIL] missing validation summary"
  exit 1
fi

if ! grep -q '"status": "pass"' data/sessions/c01/validation-summary-baseline.json; then
  echo "[FAIL] baseline validator did not pass"
  exit 1
fi

if ! grep -q '"status": "pass"' data/sessions/c01/validation-summary-polarity.json; then
  echo "[FAIL] polarity validator did not pass"
  exit 1
fi

cat > data/sessions/c01/validation-summary.json << 'EOF'
{
  "chunk": "C01",
  "status": "pass",
  "artifacts": [
    "data/sessions/c01/validation-summary-baseline.json",
    "data/sessions/c01/validation-summary-polarity.json"
  ]
}
EOF

if ! grep -q '"status": "pass"' data/sessions/c01/validation-summary.json; then
  echo "[FAIL] validator did not pass"
  exit 1
fi

echo "[PASS] C01 tooling verification passed (synthetic harness)"
