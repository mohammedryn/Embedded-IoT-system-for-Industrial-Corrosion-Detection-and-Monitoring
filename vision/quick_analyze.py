#!/usr/bin/env python3
"""Quick image capture and Gemini analysis - single command."""
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
except ModuleNotFoundError:
    # Support direct execution: python vision/quick_analyze.py
    from gemini_client import GeminiVisionClient


def _find_recent_image(capture_dir: Path, start_time: float) -> Path | None:
    """Find the newest non-empty capture candidate created after start_time."""
    candidates: list[Path] = []
    for p in capture_dir.iterdir():
        if not p.is_file():
            continue
        # Some rpicam builds may emit files with odd names (e.g., trailing dot).
        # Accept any non-empty file and let normalization handle final extension.
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

    # If an odd filename was produced, move it to the expected target name.
    try:
        if desired_path.exists() and desired_path != found_path:
            desired_path.unlink()
        found_path.rename(desired_path)
        return desired_path
    except OSError:
        # If rename fails (cross-device / permission), keep original path.
        return found_path


def capture_image_rpicam(output_path: Path) -> Path | None:
    """Capture image using rpicam-still (Raspberry Pi Bookworm+)."""
    try:
        start_time = time.time()
        attempts = [
            ["rpicam-still", "-o", str(output_path), "-t", "1000", "--nopreview", "--camera", "0"],
            ["rpicam-still", "-o", str(output_path), "-t", "2000", "--camera", "0"],
        ]

        for i, cmd in enumerate(attempts, start=1):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip()
                print(f"❌ rpicam-still attempt {i} failed")
                if err:
                    print(err)
                continue

            # Some camera stacks return before filesystem buffers are visible.
            for _ in range(20):
                if output_path.exists() and output_path.stat().st_size > 0:
                    return output_path
                time.sleep(0.1)

            alt = _find_recent_image(output_path.parent, start_time)
            if alt is not None:
                normalized = _normalize_capture_path(alt, output_path)
                if normalized != alt:
                    print(f"✓ Captured image normalized to: {normalized}")
                else:
                    print(f"✓ Captured image detected at alternate path: {alt}")
                return normalized

            out = (result.stdout or "").strip()
            err = (result.stderr or "").strip()
            print(f"❌ rpicam-still attempt {i} returned success but no image file was produced")
            if err:
                print(err)
            elif out:
                print(out)

        return None
    except FileNotFoundError:
        print("❌ rpicam-still not found. Install with: sudo apt install -y rpicam-apps")
        return None
    except Exception as e:
        print(f"❌ Capture failed: {e}")
        return None


def capture_image_raspistill(output_path: Path) -> Path | None:
    """Fallback: Capture using raspistill (older Pi OS)."""
    try:
        start_time = time.time()
        result = subprocess.run(["raspistill", "-o", str(output_path)], capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            if err:
                print(err)
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
        description="Capture image + analyze with Gemini",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python vision/quick_analyze.py              # Capture now, analyze
  python vision/quick_analyze.py --file image.jpg  # Analyze existing image
  python vision/quick_analyze.py --output results.json  # Save JSON to file
""",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Use existing image file instead of capturing"
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
        help="Save JSON results to file"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full JSON output"
    )
    
    args = parser.parse_args()

    # Determine image path
    if args.file:
        image_path = Path(args.file)
        if not image_path.exists():
            print(f"❌ Image file not found: {image_path}")
            sys.exit(1)
        print(f"📷 Using image: {image_path}")
    else:
        # Capture new image
        project_root = Path(__file__).resolve().parents[1]
        capture_dir = project_root / "data" / "captures"
        capture_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        image_path = capture_dir / f"capture-{timestamp}.jpg"
        
        print(f"📷 Capturing image to {image_path}...")
        
        captured_path = capture_image_rpicam(image_path) or capture_image_raspistill(image_path)
        if captured_path is None:
            print("\n⚠️  Could not capture image. \n")
            print("If you're NOT on a Raspberry Pi:")
            print("  Use: python vision/quick_analyze.py --file sample.jpg\n")
            print("If you ARE on a Raspberry Pi:")
            print("  Make sure camera is connected and enabled:")
            print("    sudo raspi-config nonint do_camera 0  # Enable camera")
            print("    rpicam-hello --list-cameras  # Detect camera")
            print("    rpicam-hello -t 0  # Preview/test camera\n")
            sys.exit(1)

        image_path = captured_path
        
        print(f"✓ Image captured: {image_path}")

    # Initialize Gemini client
    try:
        client = GeminiVisionClient(api_key=args.api_key, model_id=args.model)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Analyze image
    print("🔍 Analyzing with Gemini...")
    result = client.analyze_image_file(image_path)

    if "error" in result:
        print(f"\n❌ Analysis failed: {result['error']}")
        if args.verbose:
            print(f"Details: {result.get('details', 'No details')}")
        sys.exit(1)

    # Display results
    print("\n" + "="*60)
    print("GEMINI ANALYSIS RESULTS")
    print("="*60)
    
    if "text_summary" in result:
        print(f"\n📝 Summary:\n   {result['text_summary']}")
    
    if "rust_coverage_estimate" in result:
        print(f"\n🔧 Rust Coverage: {result['rust_coverage_estimate'].upper()}")
    
    if "surface_condition" in result:
        print(f"   Surface: {result['surface_condition']}")
    
    if "severity_0_to_10" in result:
        severity = result["severity_0_to_10"]
        confidence = result.get("confidence_0_to_1", 0)
        severity_bar = "█" * int(severity) + "░" * (10 - int(severity))
        print(f"\n📊 Severity: {severity_bar} {severity:.1f}/10")
        print(f"   Confidence: {confidence:.0%}")
    
    if "key_findings" in result:
        print("\n🔎 Key Findings:")
        for finding in result["key_findings"]:
            print(f"   • {finding}")
    
    if "recommendations" in result:
        print("\n💡 Recommendations:")
        for rec in result["recommendations"]:
            print(f"   • {rec}")
    
    print("\n" + "="*60)

    # Save JSON if requested
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"✓ Results saved to {output_path}")

    # Show full JSON if verbose
    if args.verbose:
        print("\nFull JSON output:")
        print(json.dumps(result, indent=2))

    # Show image path
    print(f"\n📸 Image: {image_path}")


if __name__ == "__main__":
    main()
