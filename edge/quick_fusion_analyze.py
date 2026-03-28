#!/usr/bin/env python3
"""Unified vision + potentiostat analyzer. Single command captures, measures, and analyzes."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from vision.gemini_client import GeminiVisionClient
    from edge.potentiostat_client import SyntheticSensorGenerator, PotentiostatGeminiClient
except ModuleNotFoundError:
    from gemini_client import GeminiVisionClient
    from potentiostat_client import SyntheticSensorGenerator, PotentiostatGeminiClient


def _find_recent_image(capture_dir: Path, start_time: float) -> Path | None:
    """Find the newest non-empty capture candidate created after start_time."""
    candidates: list[Path] = []
    for p in capture_dir.iterdir():
        if not p.is_file():
            continue
        try:
            if p.stat().st_size <= 0:
                continue
            if p.stat().st_mtime >= (start_time - 0.2):
                candidates.append(p)
        except OSError:
            continue

    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _normalize_capture_path(found_path: Path, desired_path: Path) -> Path:
    """Ensure captured image ends up at the desired .jpg path."""
    if found_path == desired_path:
        return found_path

    try:
        if desired_path.exists() and desired_path != found_path:
            desired_path.unlink()
        found_path.rename(desired_path)
        return desired_path
    except OSError:
        return found_path


def capture_image_rpicam(output_path: Path) -> Path | None:
    """Capture image using rpicam-still."""
    try:
        start_time = time.time()
        attempts = [
            ["rpicam-still", "-o", str(output_path), "-t", "1000", "--nopreview", "--camera", "0"],
            ["rpicam-still", "-o", str(output_path), "-t", "2000", "--camera", "0"],
        ]

        for i, cmd in enumerate(attempts, start=1):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if result.returncode != 0:
                continue

            for _ in range(20):
                if output_path.exists() and output_path.stat().st_size > 0:
                    return output_path
                time.sleep(0.1)

            alt = _find_recent_image(output_path.parent, start_time)
            if alt is not None:
                return _normalize_capture_path(alt, output_path)

        return None
    except FileNotFoundError:
        print("❌ rpicam-still not found. Install with: sudo apt install -y rpicam-apps")
        return None
    except Exception as e:
        print(f"❌ Capture failed: {e}")
        return None


def capture_image_raspistill(output_path: Path) -> Path | None:
    """Fallback capture using raspistill."""
    try:
        start_time = time.time()
        result = subprocess.run(["raspistill", "-o", str(output_path)], capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return None
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        alt = _find_recent_image(output_path.parent, start_time)
        if alt is None:
            return None
        return _normalize_capture_path(alt, output_path)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"❌ Capture failed: {e}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified vision + potentiostat analysis (capture + synthetic sensor + Gemini analysis)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python edge/quick_fusion_analyze.py              # Capture + analyze both
  python edge/quick_fusion_analyze.py --severity critical  # Force critical potentiostat state
  python edge/quick_fusion_analyze.py --output results.json  # Save combined JSON
""",
    )
    parser.add_argument(
        "--severity",
        type=str,
        choices=["healthy", "warning", "critical", "random"],
        default="random",
        help="Potentiostat severity level to simulate"
    )
    parser.add_argument(
        "--cycle-id",
        type=str,
        default="c07-fusion",
        help="Cycle ID for this measurement"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        help="Gemini API key (or set GOOGLE_API_KEY env var)"
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Gemini model ID (e.g., gemini-3-flash-preview)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Save combined JSON results to file"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full JSON output"
    )

    args = parser.parse_args()

    # Setup directories
    project_root = Path(__file__).resolve().parents[1]
    capture_dir = project_root / "data" / "captures"
    capture_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    image_path = capture_dir / f"fusion-{timestamp}.jpg"

    print("=" * 60)
    print("UNIFIED VISION + ELECTROCHEMICAL ANALYSIS")
    print("=" * 60)

    # === STEP 1: CAPTURE IMAGE ===
    print("\n📷 STEP 1: Capturing image...")
    captured_path = capture_image_rpicam(image_path) or capture_image_raspistill(image_path)
    if captured_path is None:
        print("❌ Image capture failed")
        sys.exit(1)
    print(f"✓ Image captured: {captured_path}")

    # === STEP 2: GENERATE SYNTHETIC SENSOR DATA ===
    print("\n⚡ STEP 2: Generating potentiostat data...")
    sensor_reading = SyntheticSensorGenerator.generate_reading(
        cycle_id=args.cycle_id,
        severity_mode=args.severity if args.severity != "random" else "healthy"
    )
    print(f"✓ Synthetic sensor data generated")
    print(f"   • Rp: {sensor_reading.rp_ohm:,.0f} Ω")
    print(f"   • Icorr: {sensor_reading.current_ma:.3f} mA")

    # Initialize Gemini clients
    try:
        vision_client = GeminiVisionClient(api_key=args.api_key, model_id=args.model)
        potentiostat_client = PotentiostatGeminiClient(api_key=args.api_key, model_id=args.model)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # === STEP 3: VISION ANALYSIS ===
    print("\n🔍 STEP 3: Analyzing image with Gemini (vision)...")
    vision_result = vision_client.analyze_image_file(captured_path)
    if "error" in vision_result:
        print(f"❌ Vision analysis failed: {vision_result['error']}")
        sys.exit(1)
    print("✓ Vision analysis complete")

    # === STEP 4: POTENTIOSTAT ANALYSIS ===
    print("\n🔍 STEP 4: Analyzing sensor data with Gemini (electrochemical)...")
    potentiostat_result = potentiostat_client.analyze_sensor_data(sensor_reading)
    if "error" in potentiostat_result:
        print(f"❌ Potentiostat analysis failed: {potentiostat_result['error']}")
        sys.exit(1)
    print("✓ Potentiostat analysis complete")

    # === COMBINE RESULTS ===
    fused_result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": args.cycle_id,
        "image_path": str(captured_path),
        "vision": vision_result,
        "electrochemical": potentiostat_result,
    }

    # === DISPLAY UNIFIED RESULTS ===
    print("\n" + "=" * 60)
    print("UNIFIED ANALYSIS RESULTS")
    print("=" * 60)

    print("\n🎯 VISION ANALYSIS:")
    print(f"   Text: {vision_result.get('text_summary', 'N/A')[:80]}...")
    print(f"   Rust Coverage: {vision_result.get('rust_coverage_estimate', 'N/A').upper()}")
    print(f"   Severity: {vision_result.get('severity_0_to_10', 'N/A'):.1f}/10")

    print("\n⚡ ELECTROCHEMICAL ANALYSIS:")
    print(f"   Text: {potentiostat_result.get('text_summary', 'N/A')[:80]}...")
    print(f"   Status: {potentiostat_result.get('status_band', 'N/A')}")
    print(f"   Severity: {potentiostat_result.get('electrochemical_severity_0_to_10', 'N/A'):.1f}/10")

    # Determine overall status
    vision_severity = vision_result.get('severity_0_to_10', 0)
    electrochem_severity = potentiostat_result.get('electrochemical_severity_0_to_10', 0)
    overall_severity = (vision_severity + electrochem_severity) / 2

    severity_icon = {
        0: "✓", 1: "✓", 2: "✓", 3: "✓", 4: "✓",
        5: "⚠", 6: "⚠",
        7: "🚨", 8: "🚨", 9: "🚨", 10: "🚨"
    }.get(int(overall_severity), "•")

    print(f"\n🔗 OVERALL ASSESSMENT:")
    print(f"   {severity_icon} Combined Severity: {overall_severity:.1f}/10")
    if overall_severity <= 3:
        overall_status = "HEALTHY"
    elif overall_severity <= 6:
        overall_status = "WARNING"
    else:
        overall_status = "CRITICAL"
    print(f"   Status: {overall_status}")

    print("\n" + "=" * 60)

    # Save JSON if requested
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(fused_result, f, indent=2)
        print(f"✓ Results saved to {output_path}")

    # Show full JSON if verbose
    if args.verbose:
        print("\nFull JSON output:")
        print(json.dumps(fused_result, indent=2))


if __name__ == "__main__":
    main()
