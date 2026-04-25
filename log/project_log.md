# Corrosion Monitor Project Log

**Project:** AI-Based Multi-Sensor Corrosion Detection and Remaining Life Prediction System  
**Repo:** `corrosion`  
**Log date:** 2026-04-26  
**Coverage:** Complete record — circuit development, hardware bringup, firmware, software integration, every issue encountered, how each was resolved, and the current next-step plan.

---

## 1. Executive Summary

This project builds a low-cost AI-powered corrosion monitoring system combining a custom 3-electrode potentiostat, Pi HQ camera visual inspection, and a Gemini-based multi-agent AI pipeline to detect corrosion and predict remaining useful life in real time.

### Milestones reached

**Hardware (C01 — formally closed 2026-04-19):**
- 3-op-amp potentiostat circuit designed, assembled on breadboard, and validated
- Firmware validated across 115+ measurements spanning 9 runs and 3 resistor values
- All Rp accuracy results within the PRD ±5% target
- Teensy emits canonical `FRAME:Rp:...;I:...;status:...;asym:...` over USB serial

**Software integration (completed 2026-04-25):**
- Pi serial ingestion layer built (`edge/serial_reader.py`)
- Session state layer built (`edge/session_state.py`)
- Session APIs and SSE live stream added to backend
- Dashboard crash fix applied
- 13 new tests, all passing
- Full Teensy→Pi live data path validated on real hardware

**Remaining:**
- Lab Session GUI (Step 1 Capture → Step 2 Measure → Step 3 Analyze)
- Real electrodes in NaCl solution (pending electrode availability)
- Pi HQ camera physical connection and validation

---

## 2. Project Goals and Architectural Intent

### 2.1 The original goal

A corrosion monitoring system combining:

- Electrochemical sensing via linear polarization resistance (Rp measurement)
- Vision analysis via Pi HQ Camera + Gemini
- Fusion of both modalities for severity scoring and remaining useful life (RUL) estimation
- A live operator dashboard and guided lab workflow

### 2.2 System architecture

```
Teensy 4.1
  └── MCP4725 DAC → ±10 mV sine at 0.1 Hz
  └── OPA2333 3-op-amp circuit → potentiostatic control
  └── ADS1115 ADC → reads TIA output
  └── USB serial → FRAME:Rp:...;I:...;status:...;asym:...

Raspberry Pi 5
  └── edge/serial_reader.py → parses FRAME lines
  └── edge/session_state.py → session store
  └── edge/web_server.py → HTTP + SSE
  └── vision/pipeline.py → rpicam-still + HSV + Gemini
  └── fusion/specialists.py → sensor + vision Gemini agents
  └── fusion/c06.py → weighted fusion, conflict detection, RUL
  └── fusion/c07.py → phase state machine, dashboard
  └── web/ → live dashboard UI (HTML/JS/CSS)
```

### 2.3 Chunk architecture

The project is structured as numbered implementation chunks:

| Chunk | Purpose | Status |
|-------|---------|--------|
| C00 | Bootstrap, config, logging | Done |
| C01 | Hardware bringup, firmware, resistor validation | Done (closed 2026-04-19) |
| C02 | Firmware compilation baseline | Done |
| C03 | Integration layer | Done |
| C04 | Vision pipeline | Feature complete (synthetic); awaiting real camera |
| C05 | AI specialist service | Feature complete (synthetic) |
| C06 | Fusion + RUL | Feature complete (synthetic) |
| C07 | Orchestration + dashboard | Feature complete (synthetic) |
| C08–C09 | Extended phases | Future |

---

## 3. Hardware and Circuit Development

This is the most detailed section of the log. Every stage, decision, and issue in building the potentiostat is documented here.

---

### 3.1 The circuit: what it is and why

The potentiostat is a 3-electrode electrochemical measurement instrument. Its job is to:

1. Apply a small AC perturbation (±10 mV sine at 0.1 Hz) to the electrochemical cell
2. Hold the reference electrode at that applied potential using a control amplifier
3. Measure the resulting current through the working electrode
4. Compute polarization resistance Rp = V_applied / I_peak

Rp is the key diagnostic quantity. For clean steel, Rp > 50 kΩ (passivated, low corrosion). As corrosion accelerates, Rp drops — below 1 kΩ indicates severe active corrosion.

**Why 3 electrodes?**

- **Working electrode (WE):** the steel sample being monitored
- **Reference electrode (RE):** provides a stable voltage reference; the control amplifier regulates relative to this
- **Counter electrode (CE):** carries the current injected into the solution; graphite used here to avoid contamination

---

### 3.2 Circuit progression: Stage 1 → Stage 2

#### Stage 1 (2-op-amp, resistor substitution test)

Used for C01 validation. No real electrodes. Resistors substituted in place of the electrochemical cell.

**Op-amp A (OPA2333AIDR):**
Unity-gain buffer on the DAC output. Drives the test resistor (equivalent of driving the CE in a real cell). Isolates the DAC output impedance from the cell current path.

**Op-amp B (OPA2333AIDR):**
Transimpedance amplifier (TIA). Converts the cell current to voltage.
- +IN biased at Vmid (1.65 V) via a 2×10 kΩ voltage divider from 3.3 V to GND. The midpoint (Vmid) goes to OPA2333 pin 5 (+IN).
- Rf = 100 kΩ in the feedback path (between OUT and −IN)
- ADS1115 A0 reads the TIA output in single-ended mode

**Why single-ended in Stage 1?**
No reference electrode follower exists yet. The TIA output carries a DC offset equal to Vmid + (Rf × I_DC_offset). This is visible in the ADC readings but does not affect AC Rp computation.

#### Stage 2 (3-op-amp, real electrodes)

Adds a third op-amp:

**Op-amp C (OPA2333AIDR):**
Voltage follower for the reference electrode. Its output tracks the RE potential exactly. The DAC perturbation is summed at the control amp input against this RE voltage, closing the potentiostatic control loop properly.

In Stage 2, the ADS1115 can be switched to differential mode (A0 − A1) where A1 is connected to Vmid, eliminating the DC offset from TIA readings entirely. The firmware supports runtime switching between single-ended and differential via `set mode single|diff`.

**Current state (2026-04-25):**
3-op-amp circuit is assembled and tested with a 10 kΩ//10 kΩ resistor bridge. Result: 9987 Ω measured (0.13% off nominal 10 kΩ) — better accuracy than Stage 1 results. ADC bias ~1.48 V (single-ended). ADC peak ~103 mV.

---

### 3.3 Hardware issues encountered and how they were resolved

---

#### CIRCUIT ISSUE 1: Vmid resistor divider wiring to TIA +IN

**What it is:**
In Stage 1, the TIA non-inverting input (+IN) must be held at Vmid = 1.65 V so the TIA output sits mid-rail with no input current. Without this, the TIA output either rails high or low at startup.

**Symptom if wrong:**
ADC bias reads near 0 V or near 3.3 V instead of ~1.65 V. Firmware prints `WARNING: bias < 0.5V — TIA +IN is NOT at Vmid. Check wiring.`

**Resolution:**
Two 10 kΩ resistors in series from 3.3 V to GND. Midpoint connected to OPA2333 +IN (pin 5). This creates a stiff Vmid reference. Once wired correctly, firmware printed `OK: bias is near 1.65V — Vmid wiring looks correct.` for 10 kΩ and 4.7 kΩ test resistors.

**Residual effect:**
The 2.2 kΩ test resistor case produced ADC bias at 0.94 V (well below the 1.3 V firmware threshold). This is not a wiring error — it is DC offset amplification:

```
Vbias_actual = Vmid − (Rf / Rcell) × Voffset_DAC_error
```

At Rcell = 2.2 kΩ and Rf = 100 kΩ, the ratio is 45.8×. Even a small DAC centering error (≈17 mV) gets amplified to ≈0.78 V of DC pull-down. The firmware's OK threshold (1.3 V) was calibrated for larger cell resistances and does not fire for the 2.2 kΩ case — but the AC Rp measurement is unaffected because the AC swing (±463 mV) is well within the 0–3.3 V ADC range without clipping.

**Confirmed in data:**
`bias_ok_note: "below 1.3V threshold due to DC offset amplification (Rf/Rcell=45.8x); AC measurement unaffected — no clipping confirmed"`

---

#### CIRCUIT ISSUE 2: ADC bias drifting significantly across different cell resistances

**Symptom:**
When changing from the 10 kΩ test resistor to 4.7 kΩ to 2.2 kΩ, the ADC quiescent bias dropped significantly — from ~1.48 V to ~1.31 V to ~0.94 V.

**Cause:**
The DAC output does not sit exactly at Vmid even with the center code written (code 2048 at 3.3 V/4096 = 1.6484 V). Any small centering error is amplified by Rf/Rcell in the TIA's DC gain. As Rcell decreases, the amplification increases, and the bias pulls further from 1.65 V.

| Rcell | Rf/Rcell (DC gain) | Observed bias |
|-------|--------------------|---------------|
| 10 kΩ | 10× | 1.477–1.490 V |
| 4.7 kΩ | 21× | 1.300–1.324 V |
| 2.2 kΩ | 45.8× | 0.936–0.954 V |

**Resolution:**
This is inherent to single-ended Stage 1. The fix for Stage 2 is differential ADC mode (A0 − A1) where A1 is connected to Vmid, subtracting out the DC component entirely. The bias values are physically expected and do not indicate a fault.

**Impact on measurement:**
None. The AC signal peak (the quantity used for Rp computation) sits on top of the DC bias. As long as the bias + AC peak does not clip against the supply rails (0 V or 3.3 V), the Rp result is valid. Clipping was confirmed absent in all test runs.

---

#### CIRCUIT ISSUE 3: Rf tolerance — systematic Rp under-reading

**Symptom:**
All three resistor values read consistently low by 1.8% to 3.4% compared to nominal. Initially thought to be a firmware or ADC error.

**Cause:**
Physical measurement of the feedback resistor Rf using reverse-computation from all three datasets:

```
Rf_actual = Rp_measured × Vout_peak / Vdac_peak
```

Three independent estimates all converged on **Rf_actual = 102.671 kΩ** (+2.67% over the nominal 100 kΩ value hardcoded in firmware as `RF_DEFAULT_OHM = 100000.0`).

The firmware computes:
```
Rp_calc = V_applied / I_peak
I_peak = V_TIA_peak / RF_DEFAULT_OHM
```

If RF_DEFAULT_OHM is 100 kΩ but the physical resistor is 102.671 kΩ, the firmware assumes a higher current than actually flowed, so Rp_calc comes out lower than true Rp.

| Resistor | Nominal | Measured Rp | Error | Implied Rf |
|----------|---------|-------------|-------|------------|
| 10 kΩ | 10000 | 9663.9 Ω | −3.36% | 102,340 Ω |
| 4.7 kΩ | 4700 | 4567.6 Ω | −2.81% | 102,818 Ω |
| 2.2 kΩ | 2200 | 2160.4 Ω | −1.80% | 102,876 Ω |

**Resolution:**
Systematic error confirmed as Rf tolerance. PRD target is ±5%; worst case −3.36% is within spec. Error left in place for C01 closure. The `expect <ohms>` serial command was added to firmware precisely to allow in-situ error percentage reporting without changing anything.

**Note for Stage 2:**
The 3-op-amp circuit has a different physical Rf. Use `expect 10000` (or another known resistor) to re-derive Rf_actual for the new circuit and update `RF_DEFAULT_OHM` accordingly if tighter accuracy is needed.

---

#### CIRCUIT ISSUE 4: One glitch event — transient asymmetry spike (asym = 25.6%)

**What happened:**
Run 1, measurement 7 (10 kΩ test resistor) produced:
```
Peak+: 174.783 mV  Peak-: 103.592 mV  Asymmetry: 25.6 %
WARN: asymmetry >15% — signal may be clipping on one rail.
Rp_calc: 7184.55 ohm
I_peak: 1.392 uA
FRAME:Rp:7184.55;I:1.392;status:FAIR;asym:25.6
```

Expected Rp for 10 kΩ: ~9660 Ω. Measured: 7185 Ω (28% error).

**Cause:**
Transient breadboard contact event. The positive peak shot up to 174.8 mV (nearly normal for 2.2 kΩ, not for 10 kΩ) while the negative peak remained normal at 103.6 mV. This indicates one half-cycle of the sine was disturbed — likely a brief intermittent contact on the breadboard rail connecting the test resistor. It was a one-off transient; subsequent measurements immediately returned to the expected ~103.5 mV / ~9660 Ω baseline with no intervention.

**Firmware detection:**
The firmware correctly flagged it: `WARN: asymmetry >15% — signal may be clipping on one rail.` The asymmetry threshold of 15% was chosen specifically to catch this class of event without false positives from normal measurements (max clean asymmetry was 0.7%).

**Data handling:**
The glitch measurement was marked `ASYM_GLITCH` in the CSV and excluded from statistical analysis. The validation summary records: `n_glitch_excluded: 1`, `glitch_detection: PASS`.

**Lesson:**
Breadboard connections at high impedance nodes (the TIA output, the cell connection points) are susceptible to brief contact interruptions. In the final demo setup, solder or use high-quality jumper wires with secure connections at the critical signal nodes (TIA +IN, TIA −IN, ADS1115 AIN0).

---

#### CIRCUIT ISSUE 5: I2C device not found at expected address

**Background:**
The MCP4725 DAC has a configurable I2C address via solder pad jumpers on the module. Default is 0x60, but modules with the A0 pad jumpered can appear at 0x61, 0x62, or 0x63. The ADS1115 similarly has an ADDR pin that sets its address (GND=0x48, VDD=0x49, SDA=0x4A, SCL=0x4B).

**Symptom (anticipated, handled pre-emptively):**
If the firmware tries to `dac.begin(0x60)` and the MCP4725 is at a different address, initialization fails silently or hangs.

**Resolution baked into firmware:**
The firmware does an address scan of all 4 candidate MCP4725 addresses (0x60–0x63) at startup:
```cpp
uint8_t detectMcp4725Address() {
  const uint8_t candidates[] = {0x60, 0x61, 0x62, 0x63};
  for (uint8_t i = 0; i < sizeof(candidates); i++) {
    if (i2cDevicePresent(candidates[i])) return candidates[i];
  }
  return 0;
}
```

A dedicated wiring check sketch (`firmware/mcp4725_wiring_check.ino`) was written first, before the main potentiostat firmware, specifically to confirm the DAC was visible on the I2C bus and responding to commands. This sketch toggles the DAC output between 500 and 3500 counts every 2 seconds so a multimeter can confirm the output is changing.

**Confirmed addresses across all 9 C01 runs:**
MCP4725 consistently at 0x60, ADS1115 at 0x48. Both found at every startup.

---

#### CIRCUIT ISSUE 6: DAC center code vs true Vmid mismatch

**What happened:**
The MCP4725 is a 12-bit DAC (codes 0–4095). Code 2048 nominally produces:
```
V_out = (2048 / 4095) × 3.3 V = 1.6484 V
```

This should be very close to Vmid = 1.65 V. However, the DAC has a small output offset and the Vmid resistor divider has its own tolerance (actual midpoint may be 1.64–1.66 V). These small mismatches are irrelevant for AC measurement but visibly shift the quiescent bias in single-ended mode.

**The firmware comment explains the design:**
```cpp
// Stage 1: TIA +IN must be wired to Vmid = 1.65V
// (two equal resistors, e.g. 2x10k, from 3.3V to GND; midpoint to OPA2333 pin 5)
// Stage 2: connect ADS1115 A1 to Vmid and set DIFFERENTIAL_ADC 1
```

Stage 2 eliminates this issue entirely by measuring differentially (A0 − A1), where A1 tracks the same Vmid node, cancelling any DC offset from the subtraction.

---

#### CIRCUIT ISSUE 7: Rf value in firmware vs physical Rf — potential for confusion

**Issue:**
The firmware has:
```cpp
static const float RF_DEFAULT_OHM = 100000.0f;
```

But physical measurement showed Rf_actual = 102,671 Ω. Anyone reading the code assumes 100 kΩ exactly, when the physical truth is 102.671 kΩ.

**Resolution:**
The `set rf <ohms>` serial command allows updating the Rf constant at runtime without reflashing. For precise work, after measuring Rf_actual via the `expect <ohms>` command, the operator can type `set rf 102671` and subsequent Rp_calc values will use the corrected constant.

For the C01 validation, the ±3.36% systematic error was accepted because it is within the ±5% PRD target. The notes in the validation summary explicitly document this so future work does not mistake it for instrument error.

---

#### CIRCUIT ISSUE 8: 800 µs analog settling delay per sample

**What it is:**
After each DAC code update, there is a mandatory `delayMicroseconds(800)` before the ADC sample is taken:
```cpp
dac.setVoltage(mvToDacCode(vAppliedMv), false);
delayMicroseconds(800);  // analog path settling
adcVoltsBuffer[i] = readAdcVolts();
```

**Why it exists:**
The DAC output goes through the analog control loop (op-amp A → op-amp C → CE drive), and the TIA output (op-amp B) must settle before a valid reading is taken. The RC filter at the DAC output (if present) adds further settling time. Without this delay, the ADC would capture the transient step response, not the steady-state value.

**Effect on timing:**
With 800 samples per cycle and 12.5 ms per sample target (0.1 Hz, 800 samples = 10 s per cycle), the 800 µs settling consumes 6.4% of each sample interval. The remaining ~11.7 ms is spent in ADC conversion plus the timing loop. At 800 kHz ADC rate (ADS1115 in continuous mode at 860 SPS), one conversion takes ~1.16 ms.

This is within budget. No timing violations were observed.

---

#### CIRCUIT ISSUE 9: Clipping risk at very low Rp (real electrode scenario)

**Background:**
Not encountered yet (no real electrodes in solution), but identified as a future risk during planning.

With Rf = 100 kΩ and V_applied = 10 mV:

| Rp | I_peak | V_TIA_peak |
|----|--------|------------|
| 10 kΩ | 1 µA | 100 mV |
| 1 kΩ | 10 µA | 1000 mV |
| 600 Ω | 16.7 µA | 1670 mV |
| 300 Ω | 33 µA | 3300 mV → clips |

**Clipping threshold:** approximately 600–700 Ω, accounting for the OPA2333's rail-to-rail swing limits (~50 mV from each rail on 3.3 V supply: practical max swing ≈ ±1.60 V from Vmid).

**At Rp = 1 kΩ** (severe corrosion state): V_TIA_peak = 1000 mV. This is within the ±1.60 V headroom. **No clipping at 1 kΩ.** The system is safe for the full expected corrosion progression.

**If Rp drops below ~600 Ω** (very aggressive corrosion, e.g., in strong acid): swap Rf from 100 kΩ to 10 kΩ. The firmware `set rf 10000` command allows this without reflashing.

The asymmetry detector will flag clipping before it silently corrupts readings (threshold: asymmetry > 15%).

---

#### CIRCUIT ISSUE 10: Stage 1 firmware default is single-ended; Stage 2 needs differential

**Issue:**
The firmware `#define DIFFERENTIAL_ADC 0` defaults to single-ended. For Stage 2 with real electrodes, the recommended configuration is `DIFFERENTIAL_ADC 1` (A0 − A1, where A1 is connected to Vmid). This eliminates the DC offset amplification problem (Circuit Issue 2) entirely.

**Current state:**
The 3-op-amp circuit is wired. The test with the 10k resistor bridge was done in single-ended mode (giving 9987 Ω, bias ~1.48 V, ADC peak ~103 mV). Before connecting real electrodes, the firmware should be tested with `set mode diff` to confirm the A1 connection is correct and the differential bias reads near 0 V.

---

### 3.4 Firmware development issues

---

#### FIRMWARE ISSUE 1: No I2C address scan in first iteration

**What happened:**
The first firmware iteration hardcoded `dac.begin(0x60)` without scanning. When tested on a different MCP4725 module whose pads were configured differently, it failed to initialize.

**Resolution:**
Added `detectMcp4725Address()` which scans 0x60–0x63 and uses whichever address responds. This became a permanent part of the firmware.

---

#### FIRMWARE ISSUE 2: No glitch detection in first iteration

**What happened:**
In early test runs, occasional outlier readings appeared (later confirmed as breadboard contact glitches) but were included in averages, corrupting the mean.

**Resolution:**
Added asymmetry detection: if `|Peak+ − Peak−| / avg(Peak+, Peak−) > 15%`, the firmware prints a WARN and the reading is flagged in the CSV. The validation script excludes flagged readings from statistics.

---

#### FIRMWARE ISSUE 3: Sample timing jitter at low sample counts

**What happened:**
At `set samples 100`, each sample interval is 100 ms. The timing loop used `micros()` for precision. At very low sample counts, the ADC conversion time (1.16 ms) consumed a significant fraction of each interval, and the remaining time calculation produced occasional negative values (integer underflow in microsecond arithmetic).

**Resolution:**
Added clamping: if `elapsedUs >= targetUs`, skip the delay (don't subtract). This ensures the loop never sleeps for a negative duration. At 800 samples (the default), this is never an issue.

---

#### FIRMWARE ISSUE 4: `bias` command threshold not appropriate for 2.2 kΩ case

**What happened:**
The firmware printed no confirmation message when the 2.2 kΩ test resistor was connected, because the bias (0.94 V) was below the `> 1.3V` threshold for printing "OK: bias is near 1.65V." This caused confusion — it looked like a wiring error.

**Resolution:**
The validation report documents this as expected behaviour. The threshold of 1.3 V is calibrated for moderate cell resistances. For very low Rp cells in Stage 2, differential mode (which always reads near 0 V at quiescent) is the correct operating mode and its threshold is `|bias| < 0.05 V`.

---

### 3.5 C01 validation methodology

Three resistors were chosen to span the expected real-world Rp range:

| Resistor | Represents electrochemically |
|----------|------------------------------|
| 10 kΩ | Active moderate corrosion (WARNING range) |
| 4.7 kΩ | Active corrosion (WARNING–SEVERE boundary) |
| 2.2 kΩ | Severe active corrosion |

Three independent runs were performed per resistor. Between runs, the Teensy was restarted to confirm I2C re-discovery and DAC/ADC re-initialization.

**Final results (C01 formal close, 2026-04-19):**

| Resistor | Rp Mean | Std Dev | Error | Result |
|----------|---------|---------|-------|--------|
| 10 kΩ | 9663.9 Ω | 27.5 Ω (0.28%) | −3.36% | PASS |
| 4.7 kΩ | 4567.6 Ω | 7.3 Ω (0.16%) | −2.81% | PASS |
| 2.2 kΩ | 2160.4 Ω | 2.7 Ω (0.13%) | −1.80% | PASS |

All within ±5% PRD target. C01 exit gate: **SIGNED OFF**.

**3-op-amp circuit result (post-C01, current build):**
10 kΩ resistor bridge → 9987 Ω measured = 0.13% error. Better than Stage 1. Circuit is ready for real electrode testing.

---

## 4. Software Development

### 4.1 What existed before the serial integration work

Before the integration sprint documented in this log, the following was present and feature-complete (working on synthetic/mock data only):

| Component | Status |
|-----------|--------|
| `edge/potentiostat_client.py` | Synthetic sensor generator (3 modes: healthy/warning/critical) |
| `vision/pipeline.py` | Full vision pipeline (quality gates, HSV, Gemini) |
| `fusion/specialists.py` | Sensor + vision Gemini specialist service |
| `fusion/c06.py` | Weighted fusion, conflict detection, RUL |
| `fusion/c07.py` | Phase state machine, dashboard state |
| `web/` | Full dashboard UI |
| `edge/web_server.py` | Basic HTTP server (no session APIs, no SSE) |
| All C05/C06/C07 smoke tests | Passing on synthetic data |

The gap: no code existed to open the Teensy serial port, parse FRAME lines, and route real Rp/I values into the pipeline.

---

### 4.2 Serial ingestion layer — `edge/serial_reader.py`

**File:** [edge/serial_reader.py](../edge/serial_reader.py) — 318 lines

**What it does:**
- Opens Teensy serial device, defaulting to `/dev/ttyACM0`
- Background reader thread: reads one line at a time, calls `parse_frame_line()`
- `parse_frame_line()`: strict regex match on `FRAME:Rp:<f>;I:<f>;status:<s>;asym:<f>` format; returns dict or raises on mismatch
- Bounded rolling buffer (`collections.deque(maxlen=N)`) of `SerialFrame` objects
- `snapshot()` → list of all buffered frames
- `frames_after(last_seq)` → incremental poll
- `wait_for_frames_after(seq, timeout_s)` → blocking wait for new data
- Callback hook: `register_callback(fn)` → called on every new frame
- Reconnect/backoff: if port disconnects, waits and retries

**Parsing contract (canonical format):**
```text
FRAME:Rp:307692.28;I:0.033;status:EXCELLENT;asym:0.7
```

Non-FRAME lines (Teensy startup banner, measurement config printouts, bias readouts) are logged as `serial_parse_error` warnings and discarded. They do not become readings.

---

### 4.3 Session state layer — `edge/session_state.py`

**File:** [edge/session_state.py](../edge/session_state.py) — 108 lines

**What it does:**
- Thread-safe in-memory store for the active lab session
- `new_session()` → generates UUID, clears photos + readings
- `add_photo(path)` / `remove_photo(id)` / `list_photos()`
- `add_reading(reading)` → appends to bounded deque
- `latest_reading()` → most recent frame dict
- `readings_snapshot()` → ordered list of all collected readings
- Singleton `session_state` object used by the backend

---

### 4.4 Backend API integration — `edge/web_server.py`

**File:** [edge/web_server.py](../edge/web_server.py) — 275 lines (updated)

**Endpoints added:**

| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/session/new` | POST | Creates session ID, clears state |
| `/api/session/serial/connect` | POST | Opens `/dev/ttyACM0` at 115200, starts FRAME reader thread |
| `/api/session/serial/disconnect` | POST | Closes serial port cleanly |
| `/api/session/readings` | GET | JSON snapshot of all collected readings |
| `/api/session/readings/stream` | GET | SSE stream (`text/event-stream`); emits `event: reading` per FRAME |

**Other changes:**
- Switched to `ThreadingHTTPServer` so SSE does not block other requests
- `allow_reuse_address = True` prevents `Address already in use` on restart
- Safe fallback loader for `dashboard-latest.json` (see Issue 4.7 below)

---

### 4.5 Test coverage

Three new test files were added:

| File | What it covers |
|------|---------------|
| `tests/test_serial_reader.py` | FRAME parsing, malformed rejection, numeric edge cases, thread-safe ingest, bounded buffer |
| `tests/test_session_state.py` | Session reset, photo CRUD, reading deque, bounded history |
| `tests/test_web_session_api.py` | API connect/disconnect, snapshot endpoint, SSE contract |

**Result: 13 tests, all passing in 2.08 s.**

---

## 5. Issues Encountered — Software

---

### 5.1 Port 8080 already in use on restart

**Symptom:**
```
OSError: [Errno 98] Address already in use
```

**Cause:**
A prior server process had not fully released the port before restart. Common during rapid development iteration.

**Resolution:**
- Switched to `ThreadingHTTPServer` with `allow_reuse_address = True`
- One-time cleanup: `fuser -k 8080/tcp` to kill stale listener

**Outcome:** Server restarts cleanly.

---

### 5.2 `pytest` not available as a direct command on Pi

**Symptom:**
```
bash: pytest: command not found
```

**Cause:**
The virtualenv bin directory was not in PATH when running pytest directly.

**Resolution:**
```bash
python3 -m pytest
```

---

### 5.3 `pyserial` missing in Pi virtualenv

**Symptom:**
```
serial_connect_failed
ModuleNotFoundError: No module named 'serial'
```

**Cause:**
`pyserial` was not installed in the Pi virtual environment. It is listed in `requirements.in` but was not installed during the Pi setup.

**Resolution:**
```bash
pip install pyserial
```

Verified direct open:
```python
import serial
s = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
# → OPEN_OK /dev/ttyACM0
```

---

### 5.4 404 on `/api/session/new` after initial Pi deployment

**Symptom:**
`curl -X POST http://localhost:8080/api/session/new` returned `404 Not Found`.

**Cause:**
The Pi was still running the older `web_server.py` that did not have the session endpoints. The repo was updated but the Pi copy was not pulled.

**Resolution:**
Pulled latest code on Pi, restarted server. Endpoint returned correct JSON response.

---

### 5.5 Malformed `dashboard-latest.json` crashing `/api/state`

**Symptom:**
```
json.decoder.JSONDecodeError: Extra data: line 1 column N (char N)
```
Repeated in every request to `/api/state`. Dashboard showed blank data.

**Cause:**
`dashboard-latest.json` contained concatenated JSON objects from multiple C07 orchestration runs being appended without proper overwrite. The file was not valid JSON.

**Resolution:**
Added safe fallback loading in `web_server.py`:
- Try to parse the file normally
- On any `JSONDecodeError` or `ValueError`, log a warning and return a hardcoded default state dict
- The dashboard continues running and shows defaults rather than crashing

---

### 5.6 Teensy startup chatter causing `serial_parse_error` warnings

**Symptom:**
Serial reader log flooded with:
```
serial_parse_error: "=== Teensy 4.1 Potentiostat Resistor Test v2 ==="
serial_parse_error: "Rf = 100000 ohm"
serial_parse_error: "ADC mode: single-ended (A0)"
serial_parse_error: "I2C check MCP4725 (0x60-0x63): FOUND at 0x60"
...
```

**Cause:**
The Teensy firmware prints a startup banner, I2C discovery results, bias readout, and per-measurement config summary to serial. None of these match the `FRAME:` format, so the strict parser logs them as warnings.

**Resolution:**
The parser behaviour is correct: only canonical `FRAME:` lines become readings; all other content is discarded. The warnings are noisy but harmless. The live reading data path is unaffected.

**Optional future fix:**
Add a startup-skip state in `serial_reader.py` that silently discards all lines until the first `FRAME:` is seen. This would eliminate the warning spam without changing any behaviour.

---

### 5.7 SSE blocking other HTTP requests (before ThreadingHTTPServer)

**Symptom:**
While the SSE stream was open, requests to other endpoints (e.g., `/api/session/readings`) hung until the SSE client disconnected.

**Cause:**
The original `HTTPServer` is single-threaded. An open SSE connection holds the single request-handling thread indefinitely, blocking all other requests.

**Resolution:**
Switched to `ThreadingHTTPServer`, which spawns a new thread per request. SSE connections now run in their own threads and do not block the server.

---

## 6. Pi-Side Validation Results

The following was verified on the Raspberry Pi with the Teensy 4.1 connected via USB:

| Check | Result |
|-------|--------|
| `/dev/ttyACM0` exists | ✅ |
| Python serial port opens | ✅ |
| Teensy emits valid `FRAME:` lines | ✅ |
| `POST /api/session/new` | ✅ Returns session ID |
| `POST /api/session/serial/connect` | ✅ `serial_connected: true` |
| `GET /api/session/readings/stream` | ✅ Live `event: reading` SSE events |
| `GET /api/session/readings` | ✅ Populated array, count increasing |
| `GET /api/state` | ✅ 200 OK, stable |
| Dashboard loads at `http://localhost:8080` | ✅ |

**Example live frame observed on Pi:**
```text
FRAME:Rp:307692.28;I:0.033;status:EXCELLENT;asym:0.7
```

Rp = 307,692 Ω = EXCELLENT band (> 100 kΩ). This is a dry resistor bench test (no solution), confirming the measurement path works before real electrodes are connected.

---

## 7. Files Added or Updated

### Added
- [edge/serial_reader.py](../edge/serial_reader.py) — serial ingestion layer
- [edge/session_state.py](../edge/session_state.py) — session state manager
- [tests/test_serial_reader.py](../tests/test_serial_reader.py)
- [tests/test_session_state.py](../tests/test_session_state.py)
- [tests/test_web_session_api.py](../tests/test_web_session_api.py)
- [log/project_log.md](project_log.md) — this file

### Updated
- [edge/web_server.py](../edge/web_server.py) — session APIs, SSE, threading, JSON crash fix
- [README.md](../README.md) — Teensy connection, session API quickstart, Pi troubleshooting

### Hardware artifacts (C01)
- [data/sessions/c01/10kohm_bench_runs.txt](../data/sessions/c01/10kohm_bench_runs.txt) — raw terminal output, 3 runs
- [data/sessions/c01/4p7kohm_bench_runs.txt](../data/sessions/c01/4p7kohm_bench_runs.txt) — raw terminal output, 3 runs
- [data/sessions/c01/2p2kohm_bench_runs.txt](../data/sessions/c01/2p2kohm_bench_runs.txt) — raw terminal output, 3 runs
- [data/sessions/c01/rp_measurements_real.csv](../data/sessions/c01/rp_measurements_real.csv) — structured CSV of all measurements
- [data/sessions/c01/validation-summary.json](../data/sessions/c01/validation-summary.json) — formal exit gate record

### Firmware
- [firmware/mcp4725_wiring_check.ino](../firmware/mcp4725_wiring_check.ino) — DAC wiring verification sketch (written first)
- [firmware/corrosion_potentiostat_resistor_test.ino](../firmware/corrosion_potentiostat_resistor_test.ino) — full potentiostat firmware v2 (426 lines)

---

## 8. Current Working State

### Confirmed working (real hardware, live data)
- Teensy 4.1 firmware: FRAME output, all commands functional
- Pi serial ingestion: parses live frames from `/dev/ttyACM0`
- Session APIs: new, connect, disconnect, readings, SSE stream — all functional
- Dashboard: stable, no crash on malformed JSON
- All tests: 13 passed

### Feature-complete on synthetic data only
- Vision pipeline (C04): code complete; real Pi HQ camera not yet connected
- AI specialist service (C05): code complete; not yet called with real Rp/images
- Fusion + RUL (C06): code complete; never fed real data
- Runtime orchestration + dashboard (C07): code complete; synthetic phase profiles only

### Not yet built
- Lab Session GUI (3-step stepper: Capture → Measure → Analyze)
- `/api/session/capture` and `/api/session/analyze` endpoints

### Not yet done (hardware)
- Real electrodes (WE/RE/CE) in 3.5% NaCl solution — pending electrode availability
- Pi HQ camera physical connection and `rpicam-still` validation

---

## 9. Recommended Next Steps

### Immediate (software, no hardware needed)
1. **Lab Session GUI** — add tab to `web/index.html` with 3-step stepper (Capture / Measure / Analyze). Requires new frontend panels plus `/api/session/capture` and `/api/session/analyze` backend endpoints.
2. **Startup chatter suppression** — optional: add silent-until-first-FRAME state in `serial_reader.py` to eliminate log noise.

### When electrodes are available
3. **Real electrode test** — connect WE/RE/CE to the 3-op-amp circuit, submerge in 3.5% NaCl, run `auto on`, verify Rp > 50 kΩ for clean steel. Expected: EXCELLENT status. Run `bias` command to capture Stage 2 calibration baseline.
4. **Differential ADC validation** — test `set mode diff` on the 3-op-amp circuit to confirm A1 Vmid connection and near-zero differential bias.
5. **Rf re-calibration** — use `expect 10000` with a known 10 kΩ resistor on the 3-op-amp circuit to derive new Rf_actual and update `RF_DEFAULT_OHM`.

### When camera is connected
6. **Camera validation** — connect Pi HQ Camera, run `rpicam-still --immediate`, verify `vision/pipeline.py` captures and passes quality gates (blur score ≥ 90, exposure flags clear).

### Demo preparation
7. **End-to-end live run** — with all hardware connected, trigger a full pipeline cycle: real Rp → specialist agents → fusion → dashboard display. Validate 30-minute demo phase transitions fire on correct Rp thresholds.

---

## 10. Calibration Reference — Bring-Up Checklist for Real Electrode Session

Before the first real electrode run, verify in order:

1. `bias` command → ADC quiescent bias should be near 1.65 V in single-ended mode (or near 0 V in differential mode with A1 at Vmid)
2. `expect 10000` with a known 10 kΩ resistor → confirm Rp error % and derive Rf_actual for Stage 2
3. `set rf <Rf_actual>` → correct the firmware constant for Stage 2
4. Connect electrodes to 3.5% NaCl → verify Rp > 50 kΩ for clean steel (EXCELLENT expected)
5. Add vinegar → observe Rp declining over successive 10 s cycles
6. Monitor asymmetry in FRAME output → if asym > 15% appears, check connections

Clipping guard: if Rp drops below ~600 Ω, run `set rf 10000` to switch to 10 kΩ Rf before the TIA saturates.
