# PRD: Vision Subsystem for AI-Based Corrosion Monitoring (Master-Aligned Edition)

## 1. Product Overview

The Vision Subsystem captures and analyzes steel-surface images to quantify corrosion state and provide structured visual outputs for system fusion and remaining useful life (RUL) prediction. This subsystem is explicitly constrained to run on:

- Raspberry Pi 5 (8 GB recommended)
- Pi HQ Camera (Sony IMX477)
- Ubuntu 24.04 LTS (64-bit)

The subsystem is designed for laboratory demonstrations and educational/research use, with a primary focus on robust, explainable corrosion visual assessment under limited edge compute resources.

### 1.1 Core Value

- Adds visual evidence to electrochemical measurements for cross-modal validation.
- Improves trust in final corrosion severity decisions through interpretable visual features.
- Produces machine-readable outputs for upstream fusion/orchestrator logic.
- Enables reproducible image logging for model improvement and audit trails.

---

## 2. Goals and Non-Goals

### 2.1 Goals

1. Capture stable, analyzable images of the steel working electrode throughout corrosion progression.
2. Quantify corrosion appearance using metrics such as rust coverage, pitting proxies, color shift, and surface quality.
3. Produce standardized vision severity (0-10) and confidence (0-1) for each analysis cycle.
4. Operate reliably for at least 1 hour continuously on Raspberry Pi 5 in demo mode.
5. Deliver outputs that are directly consumable by sensor-fusion and RUL pipelines.

### 2.2 Non-Goals

1. Not a certified industrial visual inspection system.
2. Not high-FPS continuous deep video inference on-device.
3. Not full 3D pit depth metrology or microscopic corrosion characterization.
4. Not multi-camera, multi-node deployment in this phase.

---

## 3. Target Users and Primary Use Cases

### 3.1 Target Users

1. Engineering students and researchers running corrosion demos.
2. Reviewers/judges evaluating embedded AI and system integration.
3. Developers extending prototype toward field-ready systems.

### 3.2 Primary Use Cases

1. Real-time corrosion demo progression from clean steel to severe corrosion.
2. Fresh-vs-corroded sample comparison with strong visual contrast.
3. Time-series image logging for offline analysis and model iteration.
4. Correlation analysis between visual metrics and electrochemical signals.

---

## 4. Platform and Environment Constraints

### 4.1 Hardware Constraints

- Compute: Raspberry Pi 5 (ARM Cortex-A76, 8 GB RAM target profile).
- Camera: Pi HQ Camera with C/CS lens and fixed mount.
- Lighting: External controlled light source is mandatory for repeatability.

### 4.2 OS and Runtime Constraints

- Operating System: Ubuntu 24.04 LTS (64-bit).
- Camera stack: libcamera/picamera2 (with command-line fallback support for rpicam-still and libcamera-still).
- Runtime target: Python-based orchestration with asynchronous specialist execution and structured JSON outputs.

### 4.3 Raspberry Pi 5 Deployment Constraints

1. Inference must be still-image based, not real-time video inference.
2. Default analysis must use ROI-first processing to preserve deterministic latency across long runs.
3. Capture cadence must be matched to sensor cycles, not maximum camera throughput.
4. Thermal and memory headroom must be preserved to avoid throttling and instability.
5. Default capture schedule shall remain aligned to the 10-second electrochemical cycle.

---

## 5. Scope and System Interfaces

### 5.1 In Scope

1. Camera initialization, control, and scheduled capture.
2. Image quality validation (focus/exposure checks).
3. ROI handling and preprocessing.
4. Corrosion visual feature extraction.
5. Severity/confidence computation.
6. Structured output generation for fusion subsystem.
7. Logging, diagnostics, and degraded-mode behavior.

### 5.2 Out of Scope

1. Electrochemical signal processing internals (Rp/current computation).
2. Full fusion/orchestrator policy internals beyond I/O contract compatibility.
3. Industrial certification workflows.

### 5.3 Inputs

1. Capture trigger (periodic or event-driven).
2. Timestamp and cycle ID.
3. Optional electrochemical context: Rp, current, status label.
4. Session calibration profile (ROI, exposure, white-balance settings).

### 5.4 Outputs

1. Rust coverage percentage and category.
2. Pitting proxy count/severity band.
3. Surface quality class.
4. Dominant corrosion color class.
5. Corrosion morphology class (uniform vs localized).
6. Visual severity score (0-10).
7. Confidence score (0-1).
8. Quality flags and degraded-mode indicators.

### 5.5 Specialist and Fusion Interface Alignment

1. Vision outputs shall be compatible with the Vision Specialist -> Fusion Agent contract in the master architecture.
2. Fusion-side policy assumptions that vision must support:
   - Default modality weighting: 60 percent electrochemical, 40 percent visual.
   - Conflict trigger threshold: absolute severity delta greater than 3.0.
   - Early-stage mismatch handling may temporarily shift weighting toward electrochemical evidence.
3. Vision payloads shall always include sufficient evidence fields for conflict rationale generation.
4. Cloud specialist orchestration targets Gemini 3 Flash profiles for latency and cost balance.

---

## 6. Functional Requirements

### 6.1 Camera and Capture Requirements

- FR-VIS-CAM-1: The subsystem shall initialize Pi HQ Camera and report ready state within 10 seconds of service start.
- FR-VIS-CAM-2: The subsystem shall capture still images on configured schedule aligned to the measurement cycle (default: every 10 seconds, optional every N cycles).
- FR-VIS-CAM-3: The subsystem shall support ROI-centered capture/processing focused on the steel working electrode.
- FR-VIS-CAM-4: The subsystem shall support calibration-time exposure lock and white-balance lock to minimize drift.
- FR-VIS-CAM-5: The subsystem shall attach metadata (timestamp, exposure, gain, white-balance mode, ROI ID, frame ID) to each capture.
- FR-VIS-CAM-6: The subsystem shall support a short burst mode (for example 3 frames) and select best frame using image quality score when enabled.
- FR-VIS-CAM-7: The subsystem shall support 1920x1080 still capture as the default master-aligned operating mode.
- FR-VIS-CAM-8: The subsystem shall persist captured frames in JPEG format for traceability and replay.

### 6.2 Image Quality Gate Requirements

- FR-VIS-IQ-1: The subsystem shall compute blur score and reject images below threshold.
- FR-VIS-IQ-2: The subsystem shall compute exposure quality from luminance histogram and reject under/over-exposed frames.
- FR-VIS-IQ-3: The subsystem shall retry capture up to configurable retry_count on quality failure.
- FR-VIS-IQ-4: After retry exhaustion, the subsystem shall emit degraded output with reason code and fallback-to-last-valid-frame flag.
- FR-VIS-IQ-5: The subsystem shall log quality metrics per frame for debugging and calibration.

### 6.3 Preprocessing and ROI Requirements

- FR-VIS-PRE-1: The subsystem shall normalize image orientation and crop to calibrated ROI before analysis.
- FR-VIS-PRE-2: The subsystem shall perform illumination compensation suitable for controlled lab lighting.
- FR-VIS-PRE-3: The subsystem shall apply noise reduction that preserves rust edges and pitting texture cues.
- FR-VIS-PRE-4: The subsystem shall version preprocessing pipeline and include version tag in outputs.

### 6.4 Feature Extraction Requirements

- FR-VIS-FEAT-1: The subsystem shall estimate rust coverage percentage on ROI.
- FR-VIS-FEAT-2: The subsystem shall map rust coverage to banded class: none, light, moderate, heavy.
- FR-VIS-FEAT-3: The subsystem shall compute pitting proxy metrics from local texture and anomaly response.
- FR-VIS-FEAT-4: The subsystem shall classify morphology as uniform or localized corrosion.
- FR-VIS-FEAT-5: The subsystem shall compute dominant color composition and map to corrosion color classes.
- FR-VIS-FEAT-6: The subsystem shall compute surface quality class (smooth, slightly rough, rough, heavily degraded).

### 6.5 Scoring and Explainability Requirements

- FR-VIS-SCORE-1: The subsystem shall output visual severity score in range 0 to 10.
- FR-VIS-SCORE-2: The subsystem shall output confidence score in range 0 to 1.
- FR-VIS-SCORE-3: The subsystem shall include key contributing factors in human-readable text.
- FR-VIS-SCORE-4: The subsystem shall include uncertainty drivers when confidence is below threshold.
- FR-VIS-SCORE-5: The subsystem shall support configurable smoothing over last N cycles to reduce spurious score jumps.

### 6.6 Integration Contract Requirements

- FR-VIS-INT-1: The subsystem shall publish schema-valid JSON per analysis cycle.
- FR-VIS-INT-2: The payload shall include model_version and preprocessing_version.
- FR-VIS-INT-3: The payload shall include quality_flags and degraded_mode indicators.
- FR-VIS-INT-4: Publish failure shall trigger retry and queue/backoff policy.
- FR-VIS-INT-5: On repeated publish failure, subsystem shall store local outputs for eventual sync.
- FR-VIS-INT-6: The payload shall include specialist-ready fields required by fusion for cross-modal agreement and override rationale.

---

## 7. Data Contract (Vision Output JSON)

The Vision Subsystem shall emit a JSON object with the following required fields:

1. timestamp
2. cycle_id
3. image_id
4. roi_info
5. rust_coverage_pct
6. rust_coverage_band
7. pitting_proxy_count
8. pitting_severity_band
9. surface_quality_class
10. dominant_color_class
11. morphology_class
12. visual_severity_0_to_10
13. confidence_0_to_1
14. key_findings
15. uncertainty_drivers
16. quality_flags
17. degraded_mode
18. fallback_reason
19. model_version
20. preprocessing_version

Optional extension fields:

- embedding_id
- frame_quality_score
- calibration_profile_id
- debug_artifact_path

---

## 8. Performance and Non-Functional Requirements (Raspberry Pi 5)

### 8.1 Performance

- NFR-VIS-PERF-1: Capture-to-result latency target shall be under 10 seconds nominal, with 15 seconds hard ceiling in degraded/network-affected conditions.
- NFR-VIS-PERF-2: Vision cycle shall complete within the global system cycle budget without blocking serial ingestion.
- NFR-VIS-PERF-3: Average sustained CPU utilization for vision process shall remain below 75 percent over a 30-minute demo.
- NFR-VIS-PERF-4: Memory usage shall avoid swap thrashing during continuous operation.
- NFR-VIS-PERF-5: End-to-end multimodal assessment should stay near the master-observed 8 to 10 second envelope under nominal network conditions.

### 8.2 Reliability and Robustness

- NFR-VIS-REL-1: The subsystem shall run continuously for at least 1 hour without unrecovered crash.
- NFR-VIS-REL-2: Camera disconnect/read errors shall be auto-retried with bounded retry policy.
- NFR-VIS-REL-3: Network/model timeout shall trigger degraded mode with transparent stale indicator.
- NFR-VIS-REL-4: All error events shall be logged with timestamp, code, and action taken.

### 8.3 Usability

- NFR-VIS-USE-1: Calibration workflow shall complete in under 5 minutes by trained student operator.
- NFR-VIS-USE-2: Key visual outputs shall be readable on projector/TV from several meters.
- NFR-VIS-USE-3: Operator should be able to trigger manual capture and view latest analyzed frame.

### 8.4 Storage and Data Management

- NFR-VIS-DATA-1: Images and JSON outputs shall be timestamped and session-organized.
- NFR-VIS-DATA-2: The subsystem shall support retention policy (for example keep last N sessions or max disk quota).
- NFR-VIS-DATA-3: On low disk space, subsystem shall alert and prune old debug artifacts first.

---

## 9. Calibration and Operating Procedure

### 9.1 Pre-Run Setup

1. Fix camera mount and lock orientation.
2. Set constant light source and reduce glare from beaker surface.
3. Position working electrode in expected ROI region.
4. Verify lens focus at operational distance.

### 9.2 Calibration Workflow

1. Capture calibration frames with clean electrode.
2. Select and lock ROI around electrode surface of interest.
3. Lock exposure and white balance under demo lighting.
4. Record calibration profile ID and store with session metadata.
5. Validate image quality gate with at least 3 consecutive acceptable frames.
6. Verify 1920x1080 still capture and metadata logging before runtime start.

### 9.3 Runtime Operation

1. Capture per schedule.
2. Run quality gate.
3. Run preprocessing and feature extraction.
4. Compute severity and confidence.
5. Emit JSON output and update UI/log.

---

## 10. Demo Flow Requirements (Vision-Specific)

### Phase A: Baseline (0-5 min)

Expected visual state:

- Clean metallic appearance (grey/silver dominant).
- Near-zero or very low rust coverage.
- Minimal pitting proxy response.
- High surface-quality class.

System expectations:

- Stable low visual severity.
- High confidence if quality gate passes consistently.

### Phase B: Accelerated Corrosion (5-10 min)

Expected visual state:

- Early discoloration and spot formation.
- Rust coverage starts rising from baseline.

System expectations:

- Detect trend increase in rust coverage band.
- Severity transitions from low toward moderate.

### Phase C: Active Corrosion (10-15 min)

Expected visual state:

- Brown/orange patches increase.
- Roughness and local anomalies become visible.

System expectations:

- Moderate severity outputs.
- Pitting proxy metrics increase and remain persistent across cycles.

### Phase D: Severe Corrosion (15-25 min)

Expected visual state:

- Heavy rust, strong orange/red dominance.
- Clear roughness and potential localized deep attack signatures.

System expectations:

- High visual severity with high confidence (if image quality good).
- Strong alignment with severe/critical sensor context.

### Phase E: Fresh-Sample Comparison (25-30 min)

Expected visual state:

- Return to clean surface characteristics.
- Sharp drop in rust and pitting indicators.

System expectations:

- Significant severity drop versus old sample.
- Clear side-by-side metric contrast shown in UI/logs.

---

## 11. Visual Correlation Rules with Electrochemical Context

The subsystem shall support explanatory correlation against Rp bands:

1. High Rp (>=50 kOhm): clean/smooth grey-silver visual class expected.
2. Medium Rp (1-10 kOhm): light/moderate brown patches and roughness expected.
3. Low Rp (<1 kOhm): heavy rust, rough/pitted surface, orange/red dominance expected.

If strong mismatch occurs, subsystem shall raise correlation_warning flag for fusion logic.

Fusion compatibility note:
1. Conflict severity delta threshold defaults to >3.0.
2. Default fusion weighting is 60 percent electrochemical and 40 percent visual.
3. Vision outputs must include key findings and uncertainty drivers to support conflict resolution narrative.

---

## 12. Error Handling and Degraded Modes

### 12.1 Error Cases

1. CAMERA_INIT_FAIL: Camera not available at startup.
2. FRAME_CAPTURE_FAIL: Capture command failed.
3. FRAME_BLUR_FAIL: Blur threshold not met.
4. FRAME_EXPOSURE_FAIL: Histogram out of acceptable range.
5. ROI_INVALID: ROI not found or unstable.
6. ANALYSIS_TIMEOUT: Processing exceeded max allowed latency.
7. PUBLISH_FAIL: Output publish failed.
8. DISK_LOW: Insufficient storage.

### 12.2 Required System Actions

1. Retry with bounded attempts and backoff.
2. Emit human-readable message and machine-readable error code.
3. Enter degraded_mode when repeated failure persists.
4. Use last-known-valid visual output with stale flag when necessary.
5. Continue logging even in degraded mode.

---

## 13. Risks, Assumptions, and Mitigations

### 13.1 Key Assumptions

1. Lighting can be controlled during demo.
2. Camera mount remains stable.
3. Network is available when cloud vision path is used.
4. Corrosion progression is visually observable in the demo window.

### 13.2 Key Risks and Mitigations

1. Lighting variability causes inconsistent metrics.
   - Mitigation: lock exposure/WB, fixed light geometry, calibration checks.

2. Reflection/glare from solution surface causes false detections.
   - Mitigation: adjust camera angle, polarizing filter if needed, matte backdrop.

3. Raspberry Pi 5 thermal throttling degrades latency during long runs.
   - Mitigation: ROI processing, reduced cadence fallback, passive/active cooling, and pre-demo thermal soak checks.

4. Cloud/API latency spikes.
   - Mitigation: timeout controls, retry, stale fallback mode.

5. False pitting from noise/compression artifacts.
   - Mitigation: quality gate + temporal smoothing + conservative confidence policy.

---

## 14. Acceptance Criteria and Verification Plan

### 14.1 Functional Acceptance

1. All FR-VIS-CAM requirements pass on target hardware.
2. All FR-VIS-IQ requirements pass with synthetic blur/exposure tests.
3. All FR-VIS-FEAT outputs present and schema-valid.
4. Scoring outputs remain bounded and stable under repeated captures.

### 14.2 Performance Acceptance

1. Median capture-to-result latency within target range.
2. Max latency below defined bound for >=95 percent of cycles in demo.
3. No serial ingestion starvation due to vision processing.

### 14.3 Reliability Acceptance

1. 1-hour endurance run with zero unrecovered crash.
2. Camera and publish failures recover according to retry policy.
3. Degraded-mode flags correctly asserted and cleared.

### 14.4 Demo Acceptance

1. Baseline-to-severe progression visible in metrics and images.
2. Fresh sample swap shows clear severity drop.
3. Logs include complete trace for each demo phase.

---

## 15. Milestones and Delivery Sequence

### M1: Camera Pipeline Foundation

- Camera init, capture scheduling, metadata logging.
- Basic quality gate and calibration profile storage.

### M2: Feature and Scoring Engine

- Rust coverage, pitting proxy, morphology/color classes.
- Severity/confidence computation and smoothing.

### M3: Integration and Resilience

- JSON schema publication to fusion input channel.
- Retry/backoff, degraded mode, local buffering.

### M4: Demo Hardening

- Phase-by-phase rehearsal.
- Performance tuning for Raspberry Pi 5.
- Acceptance checklist sign-off.

---

## 16. Implementation Notes (Advisory)

1. Prefer ROI-based processing first, full-frame only when required.
2. Keep model/lightweight pipeline modular so cloud and local paths can be swapped.
3. Version both model and preprocessing pipeline from day one.
4. Retain representative frames for each severity band for future retraining.
5. Prioritize deterministic calibration over aggressive algorithm complexity during live demo operation.
6. Keep command-level camera fallback behavior explicit for libcamera and rpicam tool variants.

---

## 17. Success Criteria (Vision Subsystem)

The vision subsystem is successful if:

1. It runs stably on Raspberry Pi 5 with Pi HQ Camera for full demo duration.
2. Visual metrics track expected corrosion evolution trends.
3. Outputs are interpretable, confidence-aware, and fusion-ready.
4. Fresh-vs-corroded comparison clearly demonstrates meaningful visual contrast.
5. Logs are sufficient to reproduce and analyze system behavior post-demo.
