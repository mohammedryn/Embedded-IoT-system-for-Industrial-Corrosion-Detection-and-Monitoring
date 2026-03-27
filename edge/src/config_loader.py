from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def _parse_value(raw: str) -> Any:
    low = raw.lower()
    if low in {"true", "false"}:
        return low == "true"
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def _set_by_path(root: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    cur: dict[str, Any] = root
    for key in parts[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _apply_env_overrides(cfg: dict[str, Any], prefix: str = "CORR__") -> dict[str, Any]:
    for key, raw in os.environ.items():
        if not key.startswith(prefix):
            continue
        dotted = key[len(prefix):].lower().replace("__", ".")
        _set_by_path(cfg, dotted, _parse_value(raw))
    return cfg


def load_settings(root_dir: str | Path) -> dict[str, Any]:
    root = Path(root_dir)
    cfg = _load_yaml(root / "config" / "settings.yaml")
    return _apply_env_overrides(cfg)


if __name__ == "__main__":
    settings = load_settings(Path(__file__).resolve().parents[2])
    print(settings)
