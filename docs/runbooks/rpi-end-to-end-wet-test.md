# Raspberry Pi End-to-End Wet Test Runbook

## Objective

Bring up the full project on a Raspberry Pi, verify the software stack, connect the Teensy potentiostat, and perform a real wet-cell corrosion test using:

- `WE`: steel sample
- `CE`: platinum electrode
- `RE`: calomel electrode

This runbook starts from a fresh clone and ends at the first valid sample reading.

## Scope and Assumptions

This runbook assumes:

1. The potentiostat circuit is already built.
2. The resistor-bridge validation is already complete.
3. The Teensy 4.1 hardware is available over USB.
4. The Raspberry Pi has network access for initial package install and Python dependency bootstrap.
5. You are running on Raspberry Pi OS or another Debian-like Linux on the Pi.

If the Teensy is already flashed with `firmware/corrosion_potentiostat_resistor_test.ino`, you can skip the firmware upload subsection and go straight to the Pi bring-up.

## Success Criteria

At the end of this run, all of the following should be true:

1. The Pi web server is running on `http://127.0.0.1:8080`.
2. The Teensy is connected on `/dev/ttyACM0` or the detected serial device.
3. The Pi is ingesting `FRAME:Rp:...;I:...;status:...` lines.
4. The steel + platinum + calomel cell produces positive, finite, repeatable `Rp` readings.
5. Optional: a session photo can be captured and analyzed.

## 1. Prepare the Raspberry Pi

Open a terminal on the Raspberry Pi and run:

```bash
sudo apt update
sudo apt install -y git curl jq python3 python3-venv python3-pip libcamera-apps
```

Why these packages:

- `git`: clone the repo
- `curl`: call the session API
- `jq`: pretty-print JSON API responses
- `python3`, `python3-venv`, `python3-pip`: create the virtual environment and install dependencies
- `libcamera-apps`: camera tools used by the capture endpoints

## 2. Clone the Repository

Choose a working directory and clone:

```bash
cd ~
git clone https://github.com/mohammedryn/Embedded-IoT-system-for-Industrial-Corrosion-Detection-and-Monitoring.git
cd Embedded-IoT-system-for-Industrial-Corrosion-Detection-and-Monitoring
```

Verify the repo root contains `README.md`, `Makefile`, `edge/`, `firmware/`, and `docs/`.

## 3. Bootstrap the Python Environment

Run the project bootstrap:

```bash
make bootstrap
```

This creates `.venv/`, upgrades `pip`, and installs the locked Python dependencies from `requirements.lock`.

When it finishes, activate the environment:

```bash
source .venv/bin/activate
```

You should now see your shell prompt prefixed by `(.venv)` or equivalent.

## 4. Run Basic Software Smoke Checks

Run the foundation smoke checks:

```bash
make smoke-c00
make smoke-c01
```

Expected outputs:

- `make smoke-c00` should end with:
  - `[PASS] C00 smoke checks passed`
- `make smoke-c01` should end with:
  - `[PASS] C01 tooling verification passed (synthetic harness)`

These do not test your real electrodes. They only confirm the project environment and validation tooling are healthy.

## 5. Optional: Configure Gemini

This step is optional. The core measurement path works without cloud AI.

If you want Gemini-enabled analysis:

```bash
export GOOGLE_API_KEY='your-real-key-here'
```

If you skip this step, the project falls back to local heuristic mode for analysis.

## 6. Flash the Teensy Firmware

If the Teensy already boots and emits `FRAME:Rp:...` lines, skip to Section 7.

### 6.1 Recommended Manual Upload Path

Use a machine with Arduino IDE 2.3.x and Teensyduino installed.

Open:

- `firmware/corrosion_potentiostat_resistor_test.ino`

Set:

1. Board: `Teensy 4.1`
2. USB Type: `Serial`
3. CPU Speed: `600 MHz`

Install libraries if prompted:

1. `Adafruit MCP4725`
2. `Adafruit ADS1X15`

Upload the sketch.

### 6.2 Important Runtime Note for Real Electrodes

For the Stage 2 real-electrode setup, the firmware supports switching ADC mode at runtime.

You do not have to edit the code if the sketch is already uploaded. Later in the test you can send:

```text
set mode diff
```

This is the correct mode when:

1. ADS1115 `A0` is reading the TIA output
2. ADS1115 `A1` is connected to `Vmid`

## 7. Give the Pi Access to the Teensy Serial Port

Add your user to the serial device group:

```bash
sudo usermod -aG dialout "$USER"
```

Log out and log back in after this, or reboot the Pi once.

Reconnect the Teensy after login and check which serial port it appears on:

```bash
ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
```

The project default is:

- `/dev/ttyACM0`

If you are unsure, unplug the Teensy, run the command, then plug it back in and run it again.

## 8. Pre-Wet-Test Wiring Map

Power off the analog board and Teensy before touching the electrodes.

Use this exact mapping:

1. `steel sample` -> `WE`
2. `platinum electrode` -> `CE`
3. `calomel electrode` -> `RE`

Keep these rules:

1. Do not swap `CE` and `RE`.
2. Do not use the calomel electrode as counter.
3. Do not let electrodes touch each other.
4. Do not let electrodes touch the beaker wall if you can avoid it.
5. Keep the calomel electrode tip close to the steel surface.
6. Keep the platinum counter a little farther away than the reference.

## 9. Prepare the Electrolyte and Sample

For a standard beaker run:

### 9.1 Make 3.5% NaCl

For `350 mL`:

```text
12.25 g NaCl + 350 mL distilled water
```

For `500 mL`:

```text
17.5 g NaCl + 500 mL distilled water
```

Procedure:

1. Pour distilled water into a clean beaker.
2. Add NaCl.
3. Stir until fully dissolved.
4. Wait 1 to 2 minutes for the liquid to settle.

### 9.2 Prepare the Steel Working Electrode

1. Clean the steel with fine sandpaper or Scotch-Brite.
2. Rinse with distilled water.
3. Wipe dry.
4. Avoid touching the cleaned area with your fingers.
5. Connect the `WE` clip to the dry upper portion of the sample.

### 9.3 Place the Electrodes

1. Insert the steel sample first.
2. Insert the calomel reference near the steel.
3. Insert the platinum counter a little farther away.
4. Keep tip spacing around `2 to 3 cm`.
5. Keep immersion depth roughly equal.
6. Fix the electrodes so they do not move during the run.

## 10. Do a Direct Serial Sanity Check First

Before starting the Pi web server, verify the Teensy is alive.

From the activated virtualenv, run:

```bash
python -m serial.tools.miniterm /dev/ttyACM0 115200
```

If your device is not `/dev/ttyACM0`, replace it with the correct one.

Expected startup behavior:

1. A Teensy boot banner appears.
2. The DAC and ADS1115 detection messages appear.
3. A startup bias check appears.
4. Auto mode may start automatically.

Type the following commands one by one:

```text
help
auto off
bias
set mode diff
bias
set amp 10
set freq 0.1
set samples 800
set rf 100000
once
```

Notes:

1. If you calibrated your physical feedback resistor already, use the real value instead of `100000`. Example:
   - `set rf 102671`
2. The second `bias` after `set mode diff` should ideally report differential bias near `0 V`.
3. `once` should produce a full measurement cycle and one `FRAME:Rp:...` line.

What you want to see:

1. Positive `Rp`
2. Finite `current`
3. No repeated fatal I2C errors
4. No continuous negative `Rp`

Exit `miniterm` with:

```text
Ctrl+]
```

Important:

- Only one process can own the serial port at a time.
- Close `miniterm` before connecting the Pi web server to the Teensy.

## 11. Start the Web Server

In Terminal 1:

```bash
cd ~/Embedded-IoT-system-for-Industrial-Corrosion-Detection-and-Monitoring
source .venv/bin/activate
python3 -m edge.web_server
```

Leave this terminal running.

Open the dashboard in a browser on the Pi:

```text
http://127.0.0.1:8080
```

If you are using another machine on the same network, replace `127.0.0.1` with the Pi IP address.

## 12. Start a New Session

In Terminal 2:

```bash
cd ~/Embedded-IoT-system-for-Industrial-Corrosion-Detection-and-Monitoring
source .venv/bin/activate
```

Create a fresh session:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/session/new | jq .
```

Expected JSON fields:

1. `"ok": true`
2. `"session_id": "..."`
3. `"photos_count": 0`
4. `"readings_count": 0`

## 13. Connect the Pi Ingestion Layer to the Teensy

Connect the serial reader:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/session/serial/connect \
  -H 'Content-Type: application/json' \
  -d '{"port":"/dev/ttyACM0","baud":115200}' | jq .
```

Expected JSON:

1. `"ok": true`
2. `"serial_connected": true`
3. `"port": "/dev/ttyACM0"`
4. `"baud": 115200`

If this fails:

1. Make sure `miniterm` is closed.
2. Make sure the Teensy is still on `/dev/ttyACM0`.
3. Make sure your user has `dialout` permissions.

## 14. Watch Live Readings

### 14.1 Snapshot Polling

Check the latest readings:

```bash
curl -sS http://127.0.0.1:8080/api/session/readings | jq .
```

Useful quick view:

```bash
curl -sS http://127.0.0.1:8080/api/session/readings | jq '.count, .latest'
```

### 14.2 Live Stream

Watch the live SSE stream:

```bash
curl -N -H 'Accept: text/event-stream' \
  'http://127.0.0.1:8080/api/session/readings/stream?last_seq=0'
```

You should see repeated `event: reading` packets with JSON payloads containing:

1. `rp_ohm`
2. `current_ua`
3. `status`
4. `asym_percent`

## 15. First Real Wet Test Procedure

With the cell already immersed and the Pi session running:

1. Wait through at least `3` full cycles.
2. Because frequency is `0.1 Hz`, each cycle is about `10 s`.
3. Do not trust the first few readings immediately after immersion.
4. Let the electrodes and fluid settle.

Then capture the baseline:

1. Record at least `10` consecutive readings.
2. Ignore the first `2 to 3` if they are still settling.
3. Use the last `5` stable `Rp` values as your baseline average.

Healthy first-run signs:

1. `Rp` is positive.
2. `Rp` stays in a reasonable band instead of jumping wildly.
3. `status` remains consistent for several cycles.
4. `asym_percent` is not persistently large.

Practical interpretation for this project:

1. `Rp > 50 kOhm`: healthy or low corrosion activity
2. `10 kOhm to 50 kOhm`: mild to moderate activity
3. `1 kOhm to 10 kOhm`: active corrosion
4. `Rp < 1 kOhm`: severe corrosion or setup issue

## 16. Optional Camera Verification

If a Pi camera is connected and working:

List cameras:

```bash
rpicam-hello --list-cameras
```

Check preview:

```bash
rpicam-hello -t 0
```

You can also hit the project preview endpoint:

```bash
curl -o preview.jpg http://127.0.0.1:8080/api/session/camera/preview
```

If the file `preview.jpg` is created and opens normally, the preview path is working.

## 17. Capture a Session Photo

Capture from the project API:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/session/capture | jq .
```

Expected JSON:

1. `"ok": true`
2. `"photo": { ... }`
3. a saved path under `data/sessions/<session_id>/photos/`

List all session photos:

```bash
curl -sS http://127.0.0.1:8080/api/session/photos | jq .
```

## 18. Run Analysis

Once you have:

1. at least `1` photo
2. at least `5` readings

Run analysis:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/session/analyze \
  -H 'Content-Type: application/json' \
  -d '{"min_readings":5}' | jq .
```

If `GOOGLE_API_KEY` is set and valid, this may use Gemini specialists.

If not, it will fall back to local heuristic mode as long as the image and readings are present.

## 19. Optional Accelerated Corrosion Demo

Only do this after a stable baseline is captured.

Procedure:

1. Keep the same beaker and electrode geometry.
2. Add `2 to 3` small drops of white vinegar.
3. Stir gently once.
4. Stop stirring and wait `30 to 60 s`.
5. Continue logging readings every cycle.

Expected behavior:

1. `Rp` trends downward over time.
2. The status may move from healthier bands toward `WARNING` or `SEVERE`.
3. Visible rust may appear after the electrochemical change begins.

## 20. What a Good End-to-End Run Looks Like

At the end of a successful run:

1. `make bootstrap` completed successfully.
2. `make smoke-c00` and `make smoke-c01` passed.
3. The Teensy serial port was detected.
4. `bias` was sensible and `set mode diff` worked.
5. The server started on port `8080`.
6. `/api/session/new` returned success.
7. `/api/session/serial/connect` returned `serial_connected: true`.
8. `/api/session/readings` showed live readings.
9. `Rp` stayed positive and physically plausible.
10. Optional capture/analyze endpoints also worked.

## 21. Common Failure Signatures

### 21.1 Serial Connect Fails

Likely causes:

1. Wrong device path
2. `dialout` permissions missing
3. Another process already owns the port

Actions:

1. Close `miniterm`
2. Recheck `/dev/ttyACM0`
3. Replug the Teensy

### 21.2 Continuous Negative Rp

Likely causes:

1. `WE` and `CE` swapped
2. Wiring polarity issue
3. Wrong analog node assignment

Actions:

1. Reconfirm `steel -> WE`
2. Reconfirm `platinum -> CE`
3. Reconfirm `calomel -> RE`

### 21.3 Very Large Flat Rp

Likely causes:

1. Poor immersion
2. Weak or incorrectly mixed NaCl solution
3. Bad reference junction behavior

Actions:

1. Re-immerse electrodes
2. Re-mix fresh `3.5% NaCl`
3. Place the calomel tip closer to the steel

### 21.4 Very Noisy Readings

Likely causes:

1. Loose wires
2. Electrode motion
3. Grounding issue
4. The cell is still settling

Actions:

1. Fix the electrodes in place
2. Reseat jumpers and connectors
3. Wait several cycles before judging

## 22. Shutdown

When finished:

Disconnect the Pi serial session cleanly:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/session/serial/disconnect | jq .
```

Stop the server with `Ctrl+C` in Terminal 1.

If you want to keep using the Python environment later, reactivate it with:

```bash
cd ~/Embedded-IoT-system-for-Industrial-Corrosion-Detection-and-Monitoring
source .venv/bin/activate
```

## 23. Minimum Evidence to Save

For your report and demo evidence, save:

1. Screenshot of successful `make smoke-c00`
2. Screenshot of successful `make smoke-c01`
3. One serial `FRAME:Rp:...` example
4. One `/api/session/readings` JSON snapshot
5. One session photo
6. Notes for solution concentration, electrode spacing, and sample identity
7. Average of the last `5` stable baseline readings

That set of artifacts is enough to show a real end-to-end run from Raspberry Pi setup to live wet-cell measurement.
