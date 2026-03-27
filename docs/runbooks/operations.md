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

## Shutdown

1. Stop services gracefully.
2. Flush logs and session artifacts.
3. Capture incident notes.
