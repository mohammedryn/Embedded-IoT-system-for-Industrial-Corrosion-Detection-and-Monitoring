# C04 Validation Report Template

## Session Metadata

- Date:
- Operator:
- Environment:
- Hardware mode: mock or real camera

## Artifact Paths

- Summary: data/sessions/c04/c04-verification-summary.json
- Results dir: data/sessions/c04/results
- Captures dir: data/sessions/c04/captures
- Logs: data/logs/vision.log

## Required Tests

1. Blur quality rejection: Pass/Fail
2. Exposure rejection: Pass/Fail
3. Valid image schema: Pass/Fail
4. Degraded fallback: Pass/Fail
5. Trend sanity (corroded > clean): Pass/Fail
6. Median latency target: Pass/Fail
7. Endurance/robustness run: Pass/Fail

## Metrics

- Median latency (ms):
- Clean severity average:
- Corroded severity average:
- Degraded fallback count:

## Limitations

- List CI vs hardware limitations.

## Final C04 Status

- C04 complete or C04 incomplete
- Blockers:
