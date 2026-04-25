# C02 Baseline Verification Artifact - Step 2 Firmware Compile Unblock and Serial Frame Sanity

Date: 2026-04-15
Scope: Minimal compile unblock and serial frame sanity smoke checks.

## Source Change Summary

- File: firmware/corrosion_potentiostat_resistor_test.ino
- Line 307 changed from `if (mcp4725Address != )` to `if (mcp4725Address != 0)`.
- Rationale: fix syntax defect in MCP4725 detection logic to restore compile correctness.
- Measurement math unchanged.
- Command interface behavior unchanged.
- Serial frame schema unchanged.

## Compile Result and Command Summary

### Attempted Teensy 4.1 compile

Command:
`arduino-cli compile --fqbn teensy:avr:teensy41 firmware/corrosion_potentiostat_resistor_test.ino`

Result:
- BLOCKED by missing toolchain in this environment.
- Terminal output:
  - `Command 'arduino-cli' not found, but can be installed with:`
  - `sudo snap install arduino-cli`

### Strongest available static validation (no Teensy toolchain present)

Commands executed:
- `g++ -std=c++17 -fsyntax-only -I<tmp-mocks> -include <tmp-mocks>/Arduino.h -x c++ firmware/corrosion_potentiostat_resistor_test.ino`
- `g++ -std=c++17 -I<tmp-mocks> -I. <tmp-mocks>/fw_host_smoke.cpp -o <tmp-mocks>/fw_host_smoke`
- `<tmp-mocks>/fw_host_smoke`

Results:
- Sketch syntax-only compile with Arduino mocks: PASS
- Host smoke executable build: PASS
- Startup/frame assertions: PASS

## Example Frame Lines Captured After Fix

Harness output:
- `startup_has_frame=no`
- `frame_line=FRAME:Rp:800.00;I:12.500;status:SEVERE`
- `frame_has_Rp=yes`
- `frame_has_I=yes`
- `frame_has_status=yes`

Interpretation:
- Startup path did not emit malformed or premature frame lines.
- Emitted frame remained parseable and backward compatible for `Rp`, `I`, and `status` fields.

## Pending for Full C02 Gate Closure

- Install Teensy compile toolchain and run native Teensy 4.1 compile.
- Flash firmware to hardware and capture real serial evidence from startup plus measurement cycles.
- Complete full C02 validation criteria outside this baseline unblock scope.
