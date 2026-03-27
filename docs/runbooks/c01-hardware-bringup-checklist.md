# C01 Hardware Bring-Up Checklist

## Objective

Validate electrochemical hardware and signal path integrity before firmware/software complexity.

## Required Tools

1. Digital multimeter.
2. Oscilloscope.
3. Raspberry Pi or workstation serial monitor.
4. Fresh steel working electrode, graphite counter electrode, Ag/AgCl reference.
5. 3.5% NaCl solution.

## Step-by-Step Checklist

### A. Pre-Power Checks

- [ ] Verify wiring against canonical map in docs/hardware/canonical-wiring-c01.md.
- [ ] Confirm no power rail short (3.3V to GND).
- [ ] Confirm common ground continuity across all modules.

Pass criteria:

1. DMM continuity and resistance checks pass.

### B. I2C Device Presence

- [ ] Detect ADS1115 on I2C bus.
- [ ] Detect MCP4725 on I2C bus.

Pass criteria:

1. Both devices respond reliably in repeated scans.

### C. DAC Waveform Validation

- [ ] Generate 0.1 Hz sine command.
- [ ] Measure DAC/filter output with scope.
- [ ] Record Vpp, frequency, offset, and noise estimate.

Pass criteria:

1. Amplitude target: 20 mVpp with tolerance 16 to 24 mVpp.
2. Frequency target: 0.1 Hz with tolerance 0.09 to 0.11 Hz.
3. Baseline noise low enough to keep clean sinusoidal shape.

### D. ADC Baseline Stability

- [ ] Connect ADS1115 to transimpedance output.
- [ ] Acquire baseline with fresh sample and stable setup for at least 120 s.
- [ ] Record mean, standard deviation, and peak-to-peak jitter.

Pass criteria:

1. ADC values are stable with low jitter and no clipping.
2. No repeated outliers without physical stimulus.

### E. Electrode and Solution Sanity

- [ ] Confirm electrode identity and placement depth.
- [ ] Confirm 3.5% NaCl concentration.
- [ ] Confirm spacing 2 to 3 cm and no electrode contact.

Pass criteria:

1. Baseline fresh steel Rp is in expected healthy range.
2. Readings are non-zero, finite, and physically plausible.

### F. First Report Capture

- [ ] Export waveform CSV and ADC CSV.
- [ ] Run C01 validation script.
- [ ] Save report in docs/reports/c01-first-hardware-validation.md.

Pass criteria:

1. Report includes measured values, pass/fail outcomes, issues, and corrective actions.

## Exit Gate for C01

1. Three consecutive 10-minute runs pass with no hardware fault alerts.
2. Baseline fresh sample remains stable and plausible.
3. No unrecovered I2C or power-path fault during runs.
