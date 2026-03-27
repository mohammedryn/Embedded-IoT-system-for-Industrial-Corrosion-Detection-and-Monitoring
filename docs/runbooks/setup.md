# Setup Runbook

## Objective

Bring up a fresh development environment on Raspberry Pi OS or Linux workstation.

## Steps

1. Install system packages listed in `system-packages.txt`.
2. Clone repository.
3. Run `make bootstrap`.
4. Activate venv: `source .venv/bin/activate`.
5. Run smoke check: `make smoke-c00`.

## Success Criteria

- Bootstrap completes without errors.
- `make smoke-c00` prints `[PASS] C00 smoke checks passed`.
