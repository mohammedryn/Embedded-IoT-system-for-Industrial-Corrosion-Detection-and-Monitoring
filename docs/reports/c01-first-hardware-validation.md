# C01 First Hardware Validation Report

## Session Metadata

- Date: 2026-03-27
- Operator: Project Team
- Scope: C01 tooling and procedure execution
- Status: Partially complete (tooling verified, physical bench capture pending)

## 1) PRD Alignment Analysis Summary

C01 execution criteria were derived from:

1. Main PRD hardware requirements FR-HW-1 to FR-HW-5.
2. Main PRD troubleshooting requirements for negative Rp, zero output, high noise, and excessively high Rp.
3. Vision PRD platform constraints indirectly affecting C01 reliability practices (controlled setup, deterministic operation).
4. Task C01 outcome requirements in task.md.

## 2) Artifacts Produced for C01

1. Canonical wiring reference:
   - docs/hardware/canonical-wiring-c01.md
2. Hardware bring-up checklist:
   - docs/runbooks/c01-hardware-bringup-checklist.md
3. Troubleshooting decision tree:
   - docs/runbooks/c01-troubleshooting-decision-tree.md
4. Validation scripts:
   - scripts/c01_signal_validator.py
   - scripts/c01_make_synthetic_data.py
   - scripts/verify_c01.sh
5. Validation summaries:
   - data/sessions/c01/validation-summary-baseline.json
   - data/sessions/c01/validation-summary-polarity.json
   - data/sessions/c01/validation-summary.json

## 3) Measured Results (Synthetic Harness)

### Waveform check

- Peak amplitude: 0.010149 V
- Vpp: 0.020298 V
- Estimated frequency: 0.095993 Hz
- Result: Pass

### ADC baseline stability check

- Mean: 0.004500 V
- Std dev: 0.000141 V
- Peak-to-peak: 0.000399 V
- Result: Pass

### ADC polarity/correlation check

- Correlation (dac_v vs adc_v): 0.999339
- Expected sign: positive
- Result: Pass

## 4) C01 Outcome Mapping

1. Outcome: Waveform measured at expected amplitude and frequency.
   - Tooling status: Verified by synthetic harness, bench scope capture pending.
2. Outcome: ADC returns plausible values with low jitter under baseline.
   - Tooling status: Verified by synthetic harness, bench ADC capture pending.
3. Outcome: Baseline fresh sample Rp falls in expected healthy range.
   - Tooling status: Pending physical run with electrodes and solution.

## 5) Bench Execution Plan (Required to Fully Close C01)

1. Capture real waveform CSV from scope and run scripts/c01_signal_validator.py.
2. Capture real ADC baseline CSV from ADS1115 and run scripts/c01_signal_validator.py.
3. Perform three consecutive 10-minute hardware runs and document no fault alerts.
4. Fill results in this report and mark final C01 status.

## 6) Current C01 Status

- Tooling and procedure readiness: Pass
- Physical hardware validation evidence: Pending
- Final C01 exit gate: Not yet signed off until three physical 10-minute runs pass
