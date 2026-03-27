# C01 Troubleshooting Decision Tree

## Start

Symptom observed during C01 bring-up.

### 1) All readings are zero

Likely causes:

1. No 3.3V rail.
2. I2C communication failure.
3. ADC input disconnected.

Actions:

1. Verify rail voltage with DMM.
2. Re-scan I2C devices and confirm addresses.
3. Check ADS1115 input continuity from transimpedance output.

### 2) Rp is negative continuously

Likely causes:

1. Counter and working electrodes swapped.
2. Transimpedance polarity inversion.
3. Sign convention mismatch in firmware parser.

Actions:

1. Verify electrode roles physically.
2. Inspect op-amp feedback orientation.
3. Run polarity check in scripts/c01_signal_validator.py.

### 3) Rp is excessively high and flat (> 1 Mohm)

Likely causes:

1. Poor electrode immersion/contact.
2. Low salinity solution.
3. Reference electrode issue.

Actions:

1. Re-immerse electrodes to equal depth.
2. Re-mix 3.5% NaCl.
3. Verify reference electrode health and connection.

### 4) ADC is noisy/jumping

Likely causes:

1. Loose wiring.
2. Missing decoupling/grounding issues.
3. External electromagnetic coupling.

Actions:

1. Reseat all jumper wires.
2. Shorten high-impedance runs and improve ground layout.
3. Re-route cables away from noisy supplies.

### 5) DAC waveform amplitude/frequency mismatch

Likely causes:

1. Firmware parameter mismatch.
2. Filter component mismatch.
3. Scope probe scaling misconfiguration.

Actions:

1. Verify configured sine parameters.
2. Confirm R1-C1 values.
3. Recheck scope probe setting and bandwidth limit.

## Escalation

1. If unresolved after one full checklist pass, revert to known-good minimal wiring and repeat sections A to D.
2. Log incident in first validation report with timestamp, attempted fixes, and final status.
