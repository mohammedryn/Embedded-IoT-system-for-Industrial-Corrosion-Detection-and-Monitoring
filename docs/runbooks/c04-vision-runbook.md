# C04 Vision Pipeline v1 Runbook

## Objective

Execute Chunk C04 vision subsystem on Raspberry Pi 3 B+ with Pi HQ camera using ROI-first still-image analysis, quality gates, feature extraction, degraded mode, and structured outputs.

## Inputs

1. Camera profile: config/camera_profile.yaml
2. Retry policy: config/retry_policy.yaml
3. Vision pipeline: vision/pipeline.py

## Steps

1. Activate environment.
2. Run calibration lock:
   - Python API call to calibrate_and_lock_profile.
3. Execute one or more cycles using capture source (mock for CI or camera in hardware mode).
4. Inspect outputs in data/sessions/c04/results.
5. Inspect logs in data/logs/vision.log.

## Verification Commands

1. make smoke-c04
2. Validate summary file:
   - data/sessions/c04/c04-verification-summary.json

## Expected Outputs

1. Schema-valid vision JSON for each cycle.
2. Quality gate rejection for blurred and over/underexposed images.
3. Degraded mode fallback when capture retries are exhausted.
4. Trend sanity where corroded-like samples score higher than clean-like samples.

## Exit Gate Mapping

1. Median capture-to-result latency recorded and within target.
2. Quality gate test dataset passes.
3. Trend sanity passes.
4. Accelerated robustness simulation passes in CI-safe mode.

## Notes

- For hardware operation, instantiate VisionPipeline with use_mock_camera=False.
- CI mode uses synthetic images and records limitation in report.
