# PRD: AI-Based Multi-Sensor Corrosion Detection and Remaining Life Prediction System

## 1. Product Overview

This product is a low-cost, AI-powered corrosion monitoring system that combines an in-house potentiostat, camera-based visual inspection, and machine learning to detect corrosion and predict remaining life of steel structures in near real time. It targets laboratory demonstrations, educational use, and as a prototype for industrial structural health monitoring in chloride-rich environments (e.g., marine or coastal infrastructure).[^1]

Core idea:
- Use a custom 3‑electrode potentiostat to measure polarization resistance \(Rp\) of a steel working electrode immersed in 3.5% NaCl, which is directly related to corrosion rate.[^1]
- Capture high-resolution images of the metal surface to quantify rust coverage, pitting, and discoloration.[^1]
- Fuse electrochemical and visual data using a multi-agent AI architecture plus an XGBoost model to predict remaining useful life (RUL) and issue actionable health statuses (HEALTHY, WARNING, CRITICAL).[^1]

## 2. Goals and Non‑Goals

### 2.1 Product Goals

- Demonstrate a fully working end-to-end corrosion monitoring pipeline: hardware, firmware, edge compute (Raspberry Pi), and cloud AI components.[^1]
- Quantitatively track corrosion progression over time using measured \(Rp\) values and interpreted corrosion currents.[^1]
- Visually validate the electrochemical data via camera images and AI-based rust analysis (coverage, pitting severity, surface quality).[^1]
- Provide an interpretable Remaining Life (in days) prediction and severity level for the tested steel sample.[^1]
- Deliver a compelling, 30‑minute live demo script that clearly shows corrosion accelerating and the system’s response in real time.[^1]

### 2.2 Non‑Goals

- Not intended as a certified industrial safety system or replacement for standards-based inspection in the field.
- Not focused on optimizing potentiostat hardware design; the given potentiostat design is treated as fixed and in-scope only as a data source.[^1]
- Not targeting deployment across large sensor networks; this project focuses on a single-cell laboratory demonstrator.[^1]
- Not implementing complex electrochemical techniques beyond linear polarization resistance (LPR) around the corrosion potential.[^1]

## 3. Target Users and Use Cases

### 3.1 Target Users

- Engineering students and researchers who need a demonstrable, explainable corrosion monitoring setup combining hardware and AI.[^1]
- Project reviewers, judges, and faculty evaluating innovation in applied AI, embedded systems, and electrochemistry.[^1]
- Future developers who may extend this prototype to industrial field deployments.

### 3.2 Primary Use Cases

- **UC1 – Real-Time Corrosion Demo:** User runs a 30‑minute demo where a clean steel nail is submerged, corrosion is accelerated with vinegar, and system displays evolving \(Rp\), current, severity labels, remaining life, and visual AI outputs.[^1]
- **UC2 – Baseline vs Corroded Comparison:** User compares a severely corroded sample against a fresh steel sample to validate that \(Rp\) and visual indicators differ by large factors (e.g., 50× difference in \(Rp\)).[^1]
- **UC3 – Data Logging and Trend Analysis:** System logs time series of \(Rp\), current, severity, and predictions for offline analysis or training/improving the ML model.[^1]
- **UC4 – Multi-Modal Correlation Study:** Researcher analyses how electrochemical and visual features correlate across different corrosion states and conditions.

## 4. System Context and High-Level Architecture

### 4.1 Physical Setup

The physical setup consists of:
- 500 mL glass beaker containing 3.5% NaCl solution (approx. seawater salinity).[^1]
- Three electrodes: graphite counter electrode, Ag/AgCl (or DIY) reference electrode, and steel working electrode (nail or wire) positioned with 2–3 cm spacing and all submerged in the same solution.[^1]
- Breadboard-based potentiostat circuit with op-amps (OPA2333), resistors, capacitors, and an ADS1115 ADC.[^1]
- Teensy 4.1 microcontroller generating DAC signals (via MCP4725) and reading ADC data.[^1]
- Raspberry Pi 5 connected to the Teensy via USB and to a Pi HQ camera positioned to see the steel electrode.[^1]

The beaker, electrodes, breadboard, Teensy, and Raspberry Pi are laid out on a single demo table alongside a laptop/monitor for visualization.[^1]

### 4.2 Logical Architecture

Key subsystems:
- **Potentiostat hardware subsystem** (fixed design): Generates ±10 mV sine perturbation at 0.1 Hz, controls the reference electrode at that potential, enforces current through the electrochemical cell, and converts corrosion current into a measurable voltage sent to the ADC.[^1]
- **Teensy firmware subsystem:** Controls DAC waveform, reads ADC values, computes \(Rp\) from measured peak current and applied voltage, and sends formatted data to the Raspberry Pi over serial.[^1]
- **Raspberry Pi software subsystem:** Receives data, triggers image capture, calls Gemini-based multi-agent analysis, runs XGBoost RUL model, and manages logging and UI output.[^1]
- **AI multi-agent subsystem (Gemini 3 Flash):** Orchestrator, sensor specialist, vision specialist, and fusion agent collaborate to interpret data and generate final assessment.[^1]

## 5. Functional Requirements

### 5.1 Potentiostat & Hardware (As-Is, Reference Only)

These requirements describe expected behavior; the circuit design itself is treated as fixed and not modified by this PRD.[^1]

- **FR-HW-1:** The generator shall output a clean ±10 mV sine wave at 0.1 Hz via MCP4725 DAC, filtered by an R1–C1 low-pass network to remove high frequency noise.[^1]
- **FR-HW-2:** The control amplifier (U1) shall maintain the reference electrode potential equal to the DAC signal by driving the counter electrode, implementing potentiostatic control.[^1]
- **FR-HW-3:** The electrochemical cell shall follow a Randles model with solution resistance \(R_{sol}\), polarization resistance \(R_p\), and double-layer capacitance \(C_{dl}\), representing health and corrosion state of the steel working electrode.[^1]
- **FR-HW-4:** The transimpedance amplifier (U2) shall convert corrosion current \(I_{corr}\) to voltage with gain \(V_{out} = I_{corr} \times 10 k\Omega\), supporting nanoamp-level resolution with the ADS1115.[^1]
- **FR-HW-5:** The ADS1115 shall measure current output voltage with ≈50 µV resolution, enabling current measurements down to ≈5 nA for precise \(Rp\) estimation.[^1]

### 5.2 Teensy Firmware

- **FR-MCU-1:** The Teensy shall control the MCP4725 DAC over I²C to generate the ±10 mV sine waveform with configurable amplitude and frequency (default: 0.1 Hz, ±10 mV).[^1]
- **FR-MCU-2:** The Teensy shall read the ADS1115 over the shared I²C bus at sufficient sampling rate to capture peaks of the 10 s cycle.[^1]
- **FR-MCU-3:** For each cycle, the Teensy shall:
  - Identify positive and negative peak ADC voltages.
  - Convert these voltages to peak currents using \(I_{peak} = V_{out\_peak} / 10 k\Omega\).[^1]
  - Compute \(R_p = V_{applied} / I_{peak}\) using \(V_{applied} = 0.01\,V\).[^1]
- **FR-MCU-4:** The Teensy shall classify corrosion severity into textual statuses (e.g., HEALTHY, MODERATE, WARNING, SEVERE) based on \(R_p\) thresholds provided in the interpretation guide.[^1]
- **FR-MCU-5:** The Teensy shall stream data over serial USB to the Raspberry Pi in a structured format (e.g., `Rp:<value>;I:<value>;status:<text>\n`) every measurement cycle (default: every 10 s, adjustable for slower monitoring).[^1]

### 5.3 Raspberry Pi Data Ingestion & Control

- **FR-PI-1:** The Pi shall establish a serial connection to the Teensy and continuously listen for measurement frames.[^1]
- **FR-PI-2:** On receiving a new measurement, the Pi shall:
  - Parse \(R_p\), current, and status.
  - Append the values to a time-series log with timestamps.
  - Optionally downsample or aggregate for long-term monitoring.
- **FR-PI-3:** For selected cycles (e.g., every cycle during demo), the Pi shall trigger the Pi HQ camera to capture a high-resolution image of the steel working electrode surface.[^1]
- **FR-PI-4:** The Pi shall package the latest sensor data (current \(R_p\), \(R_p\) history, current magnitude, temperature, timestamp) and image path as inputs to the AI multi-agent system.[^1]

### 5.4 AI Multi-Agent System

#### 5.4.1 Sensor Specialist Agent

- **FR-AI-SENS-1:** The sensor specialist shall accept structured electrochemical data including current \(R_p\), \(R_p\) history, computed rate of change, current magnitude, temperature, and measurement time.[^1]
- **FR-AI-SENS-2:** It shall generate a JSON output containing:
  - Technical electrochemical analysis.
  - A normalized severity score (0–10).
  - A confidence score (0–1).
  - Key findings and recommendations.
  - A `raw_data` section echoing essential metrics (e.g., \(R_p\), trend, last N values).[^1]

#### 5.4.2 Vision Specialist Agent

- **FR-AI-VIS-1:** The vision specialist shall accept an image (path or bytes) of the steel surface, and optional context such as current \(R_p\).[^1]
- **FR-AI-VIS-2:** It shall estimate rust coverage (percentage and banded category), pitting count and severity, surface quality, dominant colors, and corrosion morphology (uniform vs localized), returning them in structured JSON with a severity score and confidence.[^1]

#### 5.4.3 Fusion Agent

- **FR-AI-FUS-1:** The fusion agent shall take sensor analysis, vision analysis, and an optional XGBoost remaining life prediction as inputs.[^1]
- **FR-AI-FUS-2:** It shall perform cross-modal validation, detect and annotate conflicts between electrochemical and visual assessments, and produce a unified severity score (0–10) with an explanation.[^1]
- **FR-AI-FUS-3:** It shall estimate remaining useful life in days, with confidence intervals and main uncertainty drivers, and propose maintenance or monitoring recommendations.[^1]

#### 5.4.4 Orchestrator Agent

- **FR-AI-ORCH-1:** The orchestrator shall coordinate sensor and vision specialists in parallel using asynchronous execution to minimize latency.[^1]
- **FR-AI-ORCH-2:** It shall run conflict checks when the specialists’ severity scores differ by more than a configured threshold (e.g., >3 points on 0–10 scale).[^1]
- **FR-AI-ORCH-3:** It shall resolve conflicts by relying more on electrochemical data for early-stage subsurface corrosion and combining both modalities for advanced corrosion, recording reasoning in a human-readable decision field.[^1]
- **FR-AI-ORCH-4:** It shall expose a single, final assessment object summarizing severity, remaining life, confidence, recommendations, and detailed specialist analyses.[^1]

### 5.5 XGBoost Remaining Life Model

- **FR-ML-1:** The system shall integrate an XGBoost regression model (placeholder initially heuristic-based) that consumes electrochemical and visual features to output a baseline remaining life estimate in days.[^1]
- **FR-ML-2:** The fusion agent and orchestrator shall treat the XGBoost prediction as one input among several, not as the sole authority, and document when it is overridden due to conflicting evidence.[^1]

### 5.6 User Interface and Demo Flow

- **FR-UI-1:** A terminal or simple GUI on the Pi or external monitor shall show live data every cycle: \(R_p\), current, corrosion status, and remaining life.[^1]
- **FR-UI-2:** During the 30‑minute demo, the system shall clearly show:
  - Baseline healthy sample with high \(R_p\) and low current.
  - Gradual \(R_p\) decline and status changes as vinegar is added.
  - Severe corrosion state with low \(R_p\), high current, critical alerts, and short remaining life.
  - Comparison between corroded and fresh sample \(R_p\) values, highlighting large ratio (e.g., 56×).[^1]
- **FR-UI-3:** The interface shall display selected outputs from the Gemini and XGBoost analyses, such as rust coverage, pitting severity, and predicted remaining life with confidence.[^1]

## 6. Data Interpretation and Thresholds

### 6.1 Rp Interpretation

The product shall use the following qualitative interpretation mapping for \(R_p\) values:[^1]

| Rp Range         | Interpretation           |
|------------------|--------------------------|
| \(> 100 k\Omega\) | Excellent (pristine)     |
| 50–100 k\Omega    | Very good               |
| 10–50 k\Omega     | Good                    |
| 5–10 k\Omega      | Fair                    |
| 1–5 k\Omega       | Warning (active start)  |
| 0.5–1 k\Omega     | Severe                  |
| <0.5 k\Omega      | Critical (imminent fail)|

### 6.2 Current Interpretation

The system shall also interpret measured corrosion current \(I\) in bands:[^1]

- \(< 0.5\,\mu A\): Negligible corrosion.
- 0.5–2 µA: Slow corrosion.
- 2–10 µA: Moderate corrosion.
- 10–50 µA: Fast corrosion.
- \(> 50\,\mu A\): Very rapid corrosion.

### 6.3 Visual Correlation

The system shall maintain consistent mapping between visual state and \(R_p\) bands, for explanation and validation:[^1]

- High \(R_p\) (≥50 kΩ): clean, shiny, smooth steel; grey/silver color.
- Medium \(R_p\) (1–10 kΩ): light brown spots, slightly rough surface, brown patches.
- Low \(R_p\) (<1 kΩ): heavy rust, pitted and rough surface, orange/red rust.[^1]

## 7. Demo Scenario Requirements

The live demo shall follow the scripted flow described in the source document, with the system behavior aligning as follows:[^1]

- **Baseline (0–5 min):**
  - Display \(R_p\) in tens of kΩ and current in sub‑µA range.
  - Status: HEALTHY, with narrative explaining passive layer and low corrosion.[^1]
- **Accelerated corrosion (5–10 min):**
  - After adding vinegar, \(R_p\) should show progressive decreases every 10 s cycle.
  - UI should show declining \(R_p\) and “DECLINING” or similar message.[^1]
- **Active corrosion (10–15 min):**
  - \(R_p\) around a few kΩ, status WARNING or MODERATE.
  - AI pipeline triggered to capture image, run Gemini visual analysis, and show rust coverage/pitting results on screen.[^1]
- **Data fusion & prediction (15–20 min):**
  - Fusion agent and XGBoost produce a remaining life prediction (e.g., ~147 days) with confidence.[^1]
  - UI emphasizes combined use of electrochemical and visual features.
- **Severe corrosion (20–25 min):**
  - After further vinegar addition, \(R_p\) drops below 1 kΩ; status: SEVERE CORROSION and CRITICAL ALERT, with high current and short remaining life (e.g., ~23 days).[^1]
  - Visible rust and bubbling should be evident to audience.
- **Comparison (25–30 min):**
  - Swap in fresh steel sample.
  - UI shall quickly show new high \(R_p\) (e.g., >50 kΩ) and compare to old (e.g., 920 Ω), showing the large factor difference and validating accuracy.[^1]

## 8. Non-Functional Requirements

### 8.1 Performance

- End-to-end analysis latency (from new \(R_p\) + image capture to final AI assessment) should be under 15 s in demo mode, leveraging parallel execution of sensor and vision agents.[^1]
- The system should support continuous operation for at least 1 hour without crashes during demo sessions.

### 8.2 Reliability and Robustness

- Teensy and Pi communication should handle transient serial errors gracefully (e.g., retry, skip malformed frames).
- AI calls should be retried or gracefully degraded (e.g., show last known AI assessment) when network or API errors occur.
- Potentiostat readings should be robust to common issues like noise, poor electrode contact, and miswiring, backed by troubleshooting guidance.[^1]

### 8.3 Usability

- Setup instructions for the beaker, electrodes, and wiring should be clear enough that a student can assemble the system in under 30 minutes using a diagram and checklist.[^1]
- The demo UI should be readable at a distance of several meters on a standard projector or TV.

## 9. Error Handling and Troubleshooting

The system shall present clear messages and recommended actions when measurement anomalies occur, based on the documented troubleshooting guide:[^1]

- **Issue: Rp excessively high (>1 MΩ).**
  - Likely cause: poor electrode contact or low salinity.
  - System action: display diagnostic suggesting to check immersion depth, salt concentration, and electrode cleanliness.[^1]
- **Issue: Negative Rp readings.**
  - Likely cause: swapped counter and working electrodes or incorrect feedback polarity.
  - System action: warn user to verify wiring and op-amp configuration.[^1]
- **Issue: Rp not changing over time during expected corrosion.**
  - Likely cause: non-steel working electrode or fully rusted starting sample.
  - System action: suggest magnet test, rust removal before experiment, or adding vinegar to accelerate corrosion.[^1]
- **Issue: Highly noisy or jumping readings.**
  - Likely cause: loose connections, noise coupling, or missing decoupling capacitors.
  - System action: advise checking connections, cable routing, and grounding the beaker to circuit ground.[^1]
- **Issue: All readings zero.**
  - Likely cause: no power or DAC/I²C failure.
  - System action: prompt checks for 3.3 V supply, Teensy program, MCP4725, and ADS1115 communication.[^1]

## 10. Risks and Assumptions

### 10.1 Key Assumptions

- The potentiostat hardware operates within specified parameters and produces valid \(R_p\) values under the defined conditions.[^1]
- The 3.5% NaCl solution and vinegar additions produce observable corrosion dynamics within the 30‑minute demo window.[^1]
- Gemini 3 Flash and XGBoost can be reliably accessed from the Raspberry Pi environment.

### 10.2 Risks

- Environmental variations (temperature, electrode preparation) may affect reproducibility of \(R_p\) trajectories and remaining life estimates.
- Network/API failures during the demo may prevent AI agents from responding; mitigation includes caching or running a small subset of logic locally.
- Misinterpretation by non-technical audiences who may assume the prototype is a certified industrial tool rather than an educational demonstrator.

## 11. Success Criteria

The project is considered successful if:

- The full hardware-software pipeline runs reliably during a 30‑minute demo with live corrosion acceleration.[^1]
- \(R_p\) trends, current magnitudes, and visual changes are consistent with electrochemical expectations and the provided interpretation guide.[^1]
- The AI system provides remaining life predictions and severity labels that qualitatively track the corrosion state (healthy, moderate, severe) over time.[^1]
- Reviewers can clearly understand the multi-sensor, multi-agent architecture and recognize the innovation in combining potentiostat data, visual analysis, and AI-based life prediction.[^1]

---

## References

1. [paste.txt](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/44743173/773635e8-ec11-4dac-b22b-5dc8522c0e1a/paste.txt?AWSAccessKeyId=ASIA2F3EMEYE2WN3O53U&Signature=mkk%2BH%2F3no8Ypyq6mMGCkW%2FJ%2BzdQ%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEBYaCXVzLWVhc3QtMSJHMEUCIGYaxMAKIJ6IhARYBYWpgc8F9KAsEBxCP74S9S%2F%2FpDx6AiEAw7gRLPLYVTfsD5CO07ZV4Ys29LD9NNvGji%2FrDHD2Bjsq%2FAQI3v%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FARABGgw2OTk3NTMzMDk3MDUiDBhME5us9lduy90wSyrQBOJjqy5S7P%2Bo%2BC525yVtp6JG03Ps2iTPfTAcT87Y%2BeMI105hpuoJA6RpbI6%2FvdhHwbgG7LiTB1AdzFTkS%2BBDABBGGbrxFR%2BVWK8xbg0KLCSZ39ecfNQNJgiGzIVt7uLNpug70hbcVGMJCmu4fsD7XV7HqNR0LBwb97ydQMEPX8ktjQtMyowX6nebb6G57OLRlw9BuRvfJ1ZUyPjVITo3RF3kI7hJwoLOOohXlcMtiIVRCA9aSD8Nu1D1PI7ik3rObSgMqs5P279NBopJ6uwgpyEjY5pgooZWJVt8UJ6Afv%2B0tkUTuCpyKpsRGpv0z6PbXqhIoLgyK%2F0s%2BbRgqLlKlQwgRfyRGyjUVtmRXFpU6T633R4sTdi6PUzDsA%2Bi%2BJUcps2arRWYz6Q8vpBwIVRJ1y%2BftagwXAPrHMAQYI6Nt6s9jGxIS8pJnHHWXXw9q7FZEIQbCmiRxmpGqve6PN0Yc81C1GKiyElDPJQ5gXmrGFpIMkDj%2FlNig2MyvzEAfn%2Fhnw%2B2PRmsTpIhyIB4SnYBG2wnmyvMkSQAGEHYPc%2ByT2G0I9rNd%2BCkxzTdO8%2Fx17bHvzdXBK4%2F25mWTaLJNJAJEUY2qRT4JQ9heCV4BeMyxMpsosDj%2BMewt0VRJONoHmLjXUMcw%2FLbHQqP63eYe0hUVnA8rQUWXJFSKkmN9PW6UZrdpuCsyl0uqPuzTMXml81b7s3f3h%2B4tRQbLJkzN0z4boHk%2F8JFULj2WLaQDYXpwWiRAYV2l3Nzv3rFpPwDgH6QUFXTO6kOSNd5Sry6YYtlodkwuYaazgY6mAF93vdhy9oz8%2FhQ9pO%2Fra6RaTGuJafV1qGFbtFP604HzTbPQRJnUoAPpOFHrsQ1x3KdESVtR2kCc5RxVFpJSNEuZ%2BYlkRW9XKQ8nN%2FPPD5hjaHuFCB09PuAzmtzmNQzBnOSgBv191rv%2Birz71iGxl0bkFhfmSZmpCqvqAhXYJl3Z4vF6cQHiYrmwQX%2BXK6N37NmJS3zHj76wg%3D%3D&Expires=1774620940) - im doing this project and these are the parts of it 
please indetaily understand them first

🔬 COMPL...

