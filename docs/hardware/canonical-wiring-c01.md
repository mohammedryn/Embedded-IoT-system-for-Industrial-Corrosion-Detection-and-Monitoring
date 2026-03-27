# C01 Canonical Wiring Diagram and Pin Map

## Purpose

This document is the single canonical wiring reference for C01 hardware bring-up and signal sanity checks.

## Safety and Ground Rules

1. Power off all boards before changing wiring.
2. Use one shared ground reference across Teensy, ADS1115, MCP4725, and potentiostat signal ground.
3. Do not connect electrodes to mains earth.
4. Verify 3.3 V rails with DMM before attaching sensors.

## Core Topology

- Teensy 4.1 drives MCP4725 (DAC) over I2C.
- Teensy 4.1 reads ADS1115 (ADC) over I2C.
- MCP4725 output is filtered (R1-C1) and applied as perturbation reference.
- Potentiostat control amplifier drives counter electrode to maintain reference potential.
- Transimpedance stage output goes to ADS1115 input channel.

## I2C and Power Pin Map

Note: Use your board pin labels physically; this map is signal-level canonical.

1. Teensy 3.3V -> MCP4725 VCC
2. Teensy GND -> MCP4725 GND
3. Teensy SCL -> MCP4725 SCL
4. Teensy SDA -> MCP4725 SDA
5. Teensy 3.3V -> ADS1115 VDD
6. Teensy GND -> ADS1115 GND
7. Teensy SCL -> ADS1115 SCL
8. Teensy SDA -> ADS1115 SDA
9. ADS1115 ADDR -> GND (default address) unless collision requires remap

## Potentiostat Signal Mapping

1. MCP4725 OUT -> R1-C1 filter -> Potentiostat reference setpoint input
2. Potentiostat control amplifier output -> Counter electrode
3. Reference electrode -> Potentiostat reference sense input
4. Working electrode -> Potentiostat working node
5. Transimpedance amplifier output (Vout) -> ADS1115 AIN0
6. Optional cell/reference monitor -> ADS1115 AIN1

## Electrode Placement (Beaker)

1. Use 500 mL beaker with 3.5% NaCl.
2. Keep 2 to 3 cm separation between electrodes.
3. Ensure all electrode tips are submerged to same depth.
4. Avoid electrode contact with each other and with beaker walls.

## Wiring Verification Sequence

1. Continuity check all grounds.
2. Verify no short between 3.3V and GND.
3. Confirm I2C device discovery for MCP4725 and ADS1115.
4. Confirm DAC output generation with scope before connecting electrochemical cell.
5. Confirm ADC reads stable baseline with known input.

## Known Failure Signatures

1. Negative Rp continuously: likely polarity or electrode role swap.
2. Flat zero data: power rail, I2C, or ADC input path fault.
3. Very high Rp > 1 Mohm with no trend: poor immersion/contact or low salinity.
4. Jumping ADC values: loose wire, grounding issue, or pickup noise.
