# C04 Validation Report

## Session Metadata

- Date: 2026-03-27
- Scope: Chunk C04 only
- Source requirements: task.md C04 and visionprd.md C04 requirements
- Execution mode: CI-safe mock camera plus synthetic dataset

## Files Created and Updated (C04)

### Created

1. vision/__init__.py
2. vision/pipeline.py
3. vision/cli.py
4. scripts/c04_make_synthetic_images.py
5. scripts/verify_c04.py
6. scripts/verify_c04.sh
7. docs/runbooks/c04-vision-runbook.md
8. docs/reports/c04-validation-report-template.md
9. docs/reports/c04-validation-report.md

### Updated

1. requirements.lock
2. requirements.in
3. Makefile

## Test Results

| Test | Result | Evidence |
|---|---|---|
| Quality gate rejects blurred images | PASS | data/sessions/c04/results/t_blur.json |
| Quality gate rejects under/over-exposed images | PASS | data/sessions/c04/results/t_over.json, data/sessions/c04/results/t_under.json |
| Valid image returns schema-valid JSON | PASS | data/sessions/c04/results/t_clean_schema.json |
| Degraded mode fallback after capture failure | PASS | data/sessions/c04/results/t_forced_fail.json |
| Trend sanity (corroded severity > clean severity) | PASS | data/sessions/c04/results/trend_*.json |
| C04 smoke script | PASS | data/sessions/c04/c04-verification-summary.json |
| Median latency target | PASS | data/sessions/c04/c04-verification-summary.json |
| Accelerated robustness simulation | PASS | data/sessions/c04/results/robust_*.json |

## Key Metrics

1. Clean average severity: 0.0
2. Corroded average severity: 8.33
3. Median capture-to-result latency: 245.5 ms
4. Robustness simulation cycles: 300

## Exit Gate Assessment

1. Capture-to-result median latency in target range: PASS
2. Quality gate on dataset: PASS
3. Severity trend clean to corroded: PASS
4. No unrecovered crash criterion: CI-safe accelerated robustness simulation PASS (hardware endurance pending)

## Known Limitations

1. Physical 1-hour Pi HQ camera endurance run on Raspberry Pi hardware was not executed in CI; replaced with accelerated robustness simulation.
2. Real camera mode requires running VisionPipeline with use_mock_camera=False on Ubuntu 24.04 with libcamera/rpicam available.

## Waiver Record (Provisional Sign-Off)

1. Waiver ID: C04-WAIVER-001
2. Decision: Approved provisional progression to next chunk
3. Waived criterion: 1-hour physical camera endurance run (C04 hardware-only check)
4. Reason: Camera is operational and software verification is complete; immediate bench time not available
5. Scope impact: C04 is complete for development progression, but not fully closed for final hardware reliability sign-off
6. Mandatory follow-up before final demo:
	- One 20-30 minute real-camera rehearsal on target hardware
	- One full 1-hour real-camera endurance run with logs attached
7. Risk note: Potential long-run camera reliability/thermal issues remain until follow-up tests are completed

## Final Statement

C04 complete for implementation and verification in CI-safe mode, with provisional sign-off granted under waiver C04-WAIVER-001.

Full hardware reliability closeout remains pending until the required real-camera endurance follow-up is executed and documented.
