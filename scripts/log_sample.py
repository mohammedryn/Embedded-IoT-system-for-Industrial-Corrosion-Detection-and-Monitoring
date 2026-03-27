from __future__ import annotations

import json
import logging
from pathlib import Path

from edge.src.logging_setup import configure_logging


def main() -> None:
    configure_logging("data/logs/edge.log")
    logger = logging.getLogger("corrosion.edge")
    logger.info(
        "structured log test",
        extra={
            "event": "c00_log_smoke",
            "component": "bootstrap",
            "payload": json.dumps({"status": "ok", "cycle": 0}),
        },
    )
    print("Wrote structured sample log to data/logs/edge.log")


if __name__ == "__main__":
    main()
