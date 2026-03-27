# task.md
# World-Class Project Start Blueprint
# Project: AI-Based Multi-Sensor Corrosion Detection and Remaining Life Prediction
# Focus: End-to-end startup plan with chunk-wise execution, do's, prompt packs, and testable outcomes

meta:
  owner: Project Lead
  version: 1.0
  date: 2026-03-27
  hardware_target:
    - Raspberry Pi 5 (8GB)
    - Pi HQ Camera
    - Teensy 4.1
    - MCP4725 + ADS1115 + potentiostat board
  os_target: Ubuntu 24.04 LTS (64-bit)
  project_mode: Demo-first, reliability-focused
  definition_of_done:
    - Full 30-minute demo runs without unrecovered failure
    - Sensor + vision + fusion outputs are time-aligned and logged
    - Severity and RUL trends match expected corrosion progression

execution_rules:
  - Work chunk-by-chunk. Do not start the next chunk until current exit gate passes.
  - Every chunk must produce artifacts (code/config/docs/logs) and verification evidence.
  - Every chunk must include one rollback path and one degraded-mode behavior.
  - Keep all outputs deterministic: pinned dependencies, fixed camera settings after calibration.

quality_bars:
  reliability: "No unrecovered crash in 60-minute burn-in"
  latency: "End-to-end assessment under 10s nominal, under 15s worst-case in degraded demo mode"
  traceability: "Every decision links to logs and versioned configs"
  explainability: "Severity and confidence include human-readable drivers"

chunks:

  - id: C00
    name: Program Foundation and Repo Hygiene
    objective: Set up a reproducible development baseline and single source of truth.
    dos:
      - Define folder structure for firmware, edge app, vision, fusion, models, docs, and data logs.
      - Pin versions for Python packages and system dependencies.
      - Create runbooks: setup, troubleshooting, demo checklist.
      - Add config files for thresholds, camera profile, and retry policies.
      - Enable structured logging format from day one.
    prompts:
      - "Create a production-grade repository skeleton for a Raspberry Pi corrosion monitoring system with firmware, edge, vision, and fusion modules. Include config, scripts, docs, and tests folders."
      - "Generate a dependency lock strategy for Ubuntu 24.04 on Raspberry Pi 5 with minimal footprint and reproducible installs."
      - "Draft an operations runbook template covering startup, health checks, failure recovery, and shutdown."
    outcomes_to_test:
      - "Repo has deterministic setup with one command bootstrap."
      - "All config values load correctly and can be overridden per environment."
      - "Sample log event is emitted in structured JSON format."
    exit_gate:
      - "New team member can set up project from scratch in under 30 minutes."

  - id: C01
    name: Hardware Bring-Up and Signal Sanity
    objective: Validate electrochemical hardware and data path integrity before software complexity.
    dos:
      - Verify wiring against one canonical diagram.
      - Validate DAC waveform (amplitude/frequency/noise) and ADS1115 readings.
      - Confirm stable electrode placement and solution prep SOP.
      - Define known-good baseline readings for fresh steel sample.
      - Capture first hardware validation report.
    prompts:
      - "Produce a hardware bring-up checklist for potentiostat + Teensy + ADS1115 + MCP4725 with pass/fail criteria."
      - "Design a quick validation script to verify ADC signal stability and detect wiring polarity issues."
      - "Generate a troubleshooting decision tree for negative Rp, zero readings, and noisy measurements."
    outcomes_to_test:
      - "Waveform measured at expected amplitude and frequency."
      - "ADC returns plausible values with low jitter under baseline."
      - "Baseline fresh sample Rp falls in expected healthy range."
    exit_gate:
      - "Three consecutive 10-minute runs with stable baseline and no hardware fault alerts."

  - id: C02
    name: Firmware Cycle Engine (Teensy)
    objective: Implement deterministic measurement loop and robust serial framing.
    dos:
      - Build cycle loop: generate perturbation, sample ADC, detect peaks, compute current and Rp.
      - Implement status band mapping from Rp thresholds.
      - Implement master-aligned text frame protocol: Rp:<value>, Status:<band>, separator line.
      - Add watchdog and fault codes.
      - Include timestamp/cycle index in each frame.
    prompts:
      - "Write firmware architecture for a 10s corrosion measurement cycle with peak extraction and Rp computation."
      - "Propose a robust serial frame schema compatible with Rp:value and Status:value text lines, plus recovery from malformed frames."
      - "Create unit-like validation strategy for firmware math and threshold classification."
    outcomes_to_test:
      - "Each cycle emits one valid frame with parsable Rp and Status fields."
      - "Injected malformed frame is detected and ignored without crash."
      - "Status transitions follow threshold table with synthetic test vectors."
    exit_gate:
      - "1000 cycles simulated/observed with zero unrecovered parser desync on receiver."

  - id: C03
    name: Edge Ingestion and Time-Series Backbone (Pi)
    objective: Build a resilient ingestion service that receives, validates, stores, and serves measurement state.
    dos:
      - Implement serial listener with reconnect and frame validation.
      - Build append-only time-series storage (CSV/Parquet/SQLite).
      - Add data quality checks: monotonic timestamps, outlier flags.
      - Expose latest-state API/object for vision/fusion modules.
      - Implement retention policy and disk safety checks.
    prompts:
      - "Design a resilient serial ingestion architecture for Raspberry Pi with reconnect logic and frame quality metrics."
      - "Generate a schema for corrosion time-series logs with indexing for trend queries."
      - "Create a health-check endpoint spec for ingestion service status."
    outcomes_to_test:
      - "No data loss during serial reconnect event."
      - "Out-of-order or malformed frames are flagged and quarantined."
      - "Latest-state object updates within one cycle."
    exit_gate:
      - "30-minute continuous ingest run with complete, gap-labeled timeline."

  - id: C04
    name: Vision Pipeline v1 (Pi 5 + HQ Camera)
    objective: Achieve stable image capture, quality gating, and corrosion feature extraction aligned to master Pi 5 constraints.
    dos:
      - Calibrate and lock exposure/white-balance after setup.
      - Implement ROI-first processing and blur/exposure quality gates.
      - Extract rust coverage, pitting proxies, color/morphology classes.
      - Emit vision JSON with severity and confidence.
      - Add degraded mode: fallback to last valid frame/result.
    prompts:
      - "Build a lightweight corrosion vision pipeline for Pi 5 using still images, ROI processing, and quality gates, aligned to 10-second cycle cadence."
      - "Define a confidence model for visual severity under variable lighting and blur conditions."
      - "Generate a vision output JSON schema compatible with fusion input contracts."
    outcomes_to_test:
      - "Capture-to-result median latency stays inside vision budget."
      - "Quality gate rejects blurred/overexposed frames correctly."
      - "Each accepted cycle stores image artifacts in JPEG format with cycle metadata."
      - "Severity trend increases during induced corrosion and drops on fresh sample swap."
    exit_gate:
      - "1-hour run with no camera-service crash and consistent frame quality metrics."

  - id: C05
    name: AI Specialist Services (Sensor and Vision Analysis)
    objective: Standardize specialist outputs and confidence behavior under normal and degraded inputs.
    dos:
      - Define strict JSON schemas and validation for both specialists.
      - Align cloud specialist model baseline to Gemini 3 Flash for sensor, vision, and fusion orchestration.
      - Build prompt templates with deterministic structure.
      - Add retries, timeout policy, and stale-result fallback.
      - Record reasoning snippets and confidence drivers.
      - Version prompts and output schema.
    prompts:
      - "Create deterministic prompt templates for electrochemical and visual corrosion specialists returning schema-valid JSON only."
      - "Design timeout, retry, and fallback policy for cloud AI calls in live demos."
      - "Generate confidence calibration approach using quality flags and historical consistency."
    outcomes_to_test:
      - "Specialist responses are schema-valid across 100 test invocations."
      - "Timeout path returns valid degraded response without blocking pipeline."
      - "Confidence drops when quality flags indicate poor data."
    exit_gate:
      - "No pipeline halt under simulated API failures for 10 minutes."

  - id: C06
    name: Fusion and RUL Integration
    objective: Produce a single trustworthy assessment from sensor, vision, and model signals.
    dos:
      - Implement conflict detection using master threshold (severity delta > 3 points).
      - Define stage-aware weighting policy with default 60% electrochemical and 40% visual weighting.
      - Integrate XGBoost baseline predictor as advisory input.
      - Output unified severity, RUL, confidence interval, and rationale.
      - Log override reasons when model is overruled.
    prompts:
      - "Design a fusion policy that resolves disagreements between electrochemical and vision severity with explicit rationale."
      - "Create an explainable RUL output format with uncertainty drivers suitable for demo display."
      - "Generate synthetic scenario tests for agreement, disagreement, and noisy data conditions."
    outcomes_to_test:
      - "Fusion output remains stable with small signal noise."
      - "Conflict cases produce explicit rationale and non-empty override reason."
      - "RUL trend decreases under worsening corrosion trajectory."
    exit_gate:
      - "All scenario tests pass with expected final severity ordering."

  - id: C07
    name: UX and Demo Runtime Orchestration
    objective: Build a clear, judge-friendly live interface and phase-aware demo controls.
    dos:
      - Show live Rp/current/status/vision severity/RUL in one screen.
      - Add phase markers: baseline, acceleration, active, severe, fresh swap.
      - Include confidence and data-quality indicators.
      - Add operator controls: pause, recapture image, force recompute.
      - Add visible disclaimer: educational prototype.
    prompts:
      - "Design a minimal but high-clarity dashboard for corrosion demo audiences with large-font telemetry and alerts."
      - "Generate phase-transition messaging for a 30-minute guided demonstration."
      - "Create alert hierarchy and color rules for HEALTHY/WARNING/CRITICAL states."
    outcomes_to_test:
      - "Display is readable from projector distance."
      - "Operator can recover from one failed image cycle without restarting app."
      - "Phase transitions are visible and timestamped in logs."
    exit_gate:
      - "Dry-run demo completes with no UI lockups and clear narrative flow."

  - id: C08
    name: Reliability Engineering and Failure Drills
    objective: Hardening pass for network, camera, serial, and storage failure modes.
    dos:
      - Run fault-injection tests for serial drop, camera failure, API timeout, low disk.
      - Verify degraded mode and automatic recovery paths.
      - Add heartbeat monitoring and watchdog restart policies.
      - Validate log completeness for root-cause analysis.
      - Prepare failover script and manual runbook steps.
    prompts:
      - "Create a chaos-style fault injection plan for edge AI corrosion demo pipelines on Raspberry Pi."
      - "Define objective pass/fail criteria for recovery-time and data-loss tolerance."
      - "Generate operational runbook entries for top 10 probable demo failures."
    outcomes_to_test:
      - "Each injected failure maps to expected alert and recovery action."
      - "Recovery time remains within defined service objective."
      - "No silent data corruption under stress scenarios."
    exit_gate:
      - "All critical fault drills pass in two consecutive rehearsal sessions."

  - id: C09
    name: Validation, Sign-Off, and Demo Launch Readiness
    objective: Final integrated validation and release gate for public demonstration.
    dos:
      - Execute full 30-minute script with planned vinegar additions and sample swap.
      - Compare observed transitions against expected threshold bands.
      - Freeze versions: firmware, edge app, prompts, model, configs.
      - Produce final evidence package: logs, screenshots, metrics, incident notes.
      - Conduct final go/no-go review.
    prompts:
      - "Generate a final launch checklist with hard acceptance criteria and sign-off fields for each subsystem owner."
      - "Create a post-demo evidence report template summarizing latency, reliability, and prediction behavior."
      - "Draft an executive summary narrative for judges highlighting innovation and limitations."
    outcomes_to_test:
      - "End-to-end latency remains under target."
      - "Severity and RUL progression are directionally correct across all phases."
      - "Fresh sample comparison shows expected reset and large contrast."
    exit_gate:
      - "Go/No-Go board signs off all acceptance criteria with evidence attached."

acceptance_matrix:
  - metric: End-to-end latency
    target: "8-10s typical, < 15s worst-case demo mode"
    test_method: "Timestamp diff from sensor frame arrival to final fused output"
  - metric: Vision stability
    target: "No unrecovered crash in 60 minutes"
    test_method: "Burn-in run with continuous capture and analysis"
  - metric: Data integrity
    target: "Schema-valid outputs across full run"
    test_method: "Automated validator over all logs"
  - metric: Resilience
    target: "Graceful recovery from injected failures"
    test_method: "Fault-injection suite"
  - metric: Explainability
    target: "Every CRITICAL output includes rationale and uncertainty"
    test_method: "Output contract audit"

operating_prompts_pack:
  architecture_prompt: "Act as principal systems architect. Produce a minimal-risk design for a Raspberry Pi 5 corrosion monitoring stack with strict resource budgeting, fault tolerance, and explainability. Return modules, contracts, and run-order."
  coding_prompt: "Act as senior embedded+edge engineer. Implement the requested module with deterministic behavior, structured logs, retries, and test hooks. Keep Raspberry Pi 5 and Ubuntu 24.04 constraints explicit."
  testing_prompt: "Act as reliability lead. Generate edge-case tests, failure injections, pass/fail criteria, and expected logs for this module."
  review_prompt: "Act as a critical reviewer. Find correctness gaps, race conditions, hidden assumptions, and demo-breaking risks. Return prioritized fixes."

reporting_template:
  daily_update:
    - chunk_id
    - planned_tasks
    - completed_tasks
    - blockers
    - test_results
    - risks
    - next_day_plan

notes:
  - This plan is chunk-wise and execution-gated. Do not skip gates.
  - If a chunk fails exit gate, open a corrective mini-sprint before moving ahead.
  - Keep artifacts evidence-first: logs, metrics, screenshots, commit hashes.
