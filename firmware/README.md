# Teensy Resistor-Substitution Test (No Electrodes)

This folder contains a Teensy 4.1 sketch to validate your potentiostat signal path using known resistors instead of electrochemical electrodes.

## File

- `corrosion_potentiostat_resistor_test.ino`

## What It Verifies

- I2C communication with MCP4725 (`0x62`) and ADS1115 (`0x48`)
- DAC waveform generation (small-signal sine)
- ADC readback path from transimpedance stage
- Rp computation from applied voltage and measured current
- Serial output format for Raspberry Pi parsing (`FRAME:Rp:...;I:...;status:...`)

## Libraries Needed (Arduino/Teensyduino)

- Adafruit MCP4725
- Adafruit ADS1X15

## Wiring Notes (Resistor Substitution)

Use your existing potentiostat circuit and replace the electrochemical cell path with a known resistor network where your working-electrode path normally defines the current response.

Practical test sequence:

1. Start with `10k` test resistor (safe, stable).
2. Then try `1k`.
3. Then `100` only if your analog stage remains within range and stable.

If your analog front-end saturates at low resistance, reduce DAC amplitude in serial commands (example: `set amp 2`).

## Serial Monitor Settings

- Baud: `115200`
- Line ending: `Newline`

## Useful Commands

- `help`
- `once` (run one full cycle)
- `auto on` / `auto off`
- `set freq 0.1`
- `set amp 10`
- `set samples 800`
- `expect 10000`

## Quick Example

For a 1k resistor test:

1. Upload sketch.
2. In Serial Monitor:
   - `auto off`
   - `set amp 10`
   - `set freq 0.1`
   - `expect 1000`
   - `once`
3. Check lines:
   - `Rp_calc: ... ohm`
   - `Error: ... %`
   - `FRAME:Rp:...;I:...;status:...;expected:1000.00`

## Interpreting Results

- If measured value tracks resistor changes in the correct direction (100 ohm < 1k < 10k), your readback chain works.
- If error is large but monotonic, likely gain/offset calibration issue.
- If values are unstable, check grounding, jumper tightness, and ADS1115 input range.
