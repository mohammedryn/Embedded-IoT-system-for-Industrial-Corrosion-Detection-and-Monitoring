# Operations Runbook Template

## Startup

1. Validate power/network.
2. Activate environment.
3. Start services in order (ingestion, vision, fusion, UI).

## Health Checks

- Service heartbeat interval.
- Log freshness (< 30s).
- Error rate threshold.

## Failure Recovery

- Retry policy reference: `config/retry_policy.yaml`.
- Degraded mode behavior: retain last known valid state and flag outputs.

## C05 Specialist Verification

1. Activate environment:
   - `source .venv/bin/activate`
2. Run C05 verification:
   - `make smoke-c05`
3. Optional direct run:
   - `python scripts/verify_c05.py`

Expected terminal output:
- `[PASS] C05 smoke checks passed`

Expected artifact:
- `data/sessions/c05/c05-verification-summary.json`
- Summary contains `"status": "pass"`

## Shutdown

1. Stop services gracefully.
2. Flush logs and session artifacts.
3. Capture incident notes.
