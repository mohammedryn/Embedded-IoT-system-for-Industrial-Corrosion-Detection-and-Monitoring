from __future__ import annotations

import os
from pathlib import Path

from edge.src.config_loader import load_settings


root = Path(__file__).resolve().parents[1]
os.environ["CORR__RUNTIME__CYCLE_SECONDS"] = "12"
os.environ["CORR__PROJECT__MODE"] = "demo-override"

cfg = load_settings(root)
print(f"runtime.cycle_seconds={cfg['runtime']['cycle_seconds']}")
print(f"project.mode={cfg['project']['mode']}")
