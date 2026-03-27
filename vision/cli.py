from __future__ import annotations

import argparse
import json
from pathlib import Path

from vision.pipeline import VisionPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one vision C04 cycle")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--source-image", required=False)
    parser.add_argument("--mock-camera", action="store_true")
    parser.add_argument("--force-capture-failure", action="store_true")
    args = parser.parse_args()

    vp = VisionPipeline(
        project_root=Path(args.project_root),
        use_mock_camera=args.mock_camera,
    )
    vp.calibrate_and_lock_profile()
    result = vp.run_cycle(
        cycle_id=args.cycle_id,
        capture_source_image=args.source_image,
        force_capture_failure=args.force_capture_failure,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
