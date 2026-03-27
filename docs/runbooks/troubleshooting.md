# Troubleshooting Runbook

## Bootstrap Fails

- Symptom: pip install fails.
- Action: ensure network is available and rerun `make bootstrap`.

## Config Override Check Fails

- Symptom: smoke check says env override failed.
- Action: run `python scripts/check_config_override.py` and verify output contains overridden values.

## Structured Log Missing

- Symptom: no `data/logs/edge.log`.
- Action: run `python scripts/log_sample.py` and verify file permissions in `data/logs`.

## Next-Level Diagnostics

- Run with shell trace: `bash -x scripts/verify_c00.sh`.
