# Corrosion Monitoring Project

This repository follows chunk-wise execution from C00 onward.

## Quick Start (C00)

1. Run bootstrap:
   - `make bootstrap`
2. Run C00 smoke checks:
   - `make smoke-c00`
3. Run C01 tooling verification:
   - `make smoke-c01`

## Top-Level Structure

- firmware: Teensy firmware artifacts
- edge: Raspberry Pi ingestion/orchestration code
- vision: Vision subsystem code and models
- fusion: Fusion logic and policy
- models: ML model assets
- config: versioned YAML configuration
- scripts: setup, checks, utilities
- docs/runbooks: setup, troubleshooting, demo checklist, operations
- tests: automated tests
- data/logs: runtime logs
- data/sessions: captured session artifacts
