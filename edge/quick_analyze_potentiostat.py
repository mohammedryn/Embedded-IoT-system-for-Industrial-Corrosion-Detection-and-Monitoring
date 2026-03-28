#!/usr/bin/env python3
"""Quick potentiostat data generation and Gemini electrochemical analysis."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from edge.potentiostat_client import SyntheticSensorGenerator, PotentiostatGeminiClient
except ModuleNotFoundError:
    from potentiostat_client import SyntheticSensorGenerator, PotentiostatGeminiClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic potentiostat data and analyze with Gemini",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python edge/quick_analyze_potentiostat.py              # Generate & analyze
  python edge/quick_analyze_potentiostat.py --severity critical  # Force critical state
  python edge/quick_analyze_potentiostat.py --output results.json  # Save JSON
""",
    )
    parser.add_argument(
        "--severity",
        type=str,
        choices=["healthy", "warning", "critical", "random"],
        default="random",
        help="Corrosion severity level to simulate"
    )
    parser.add_argument(
        "--cycle-id",
        type=str,
        default="c07-potentiostat",
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
        help="Save JSON results to file"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full JSON output"
    )

    args = parser.parse_args()

    # Generate synthetic sensor reading
    print(f"⚡ Generating potentiostat data (severity: {args.severity})...")
    reading = SyntheticSensorGenerator.generate_reading(
        cycle_id=args.cycle_id,
        severity_mode=args.severity if args.severity != "random" else "healthy"
    )
    print(f"   • Rp: {reading.rp_ohm:,.0f} Ω")
    print(f"   • Icorr: {reading.current_ma:.3f} mA")
    print(f"   • Timestamp: {reading.timestamp}")

    # Initialize Gemini client
    try:
        client = PotentiostatGeminiClient(api_key=args.api_key, model_id=args.model)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Analyze sensor data
    print("🔍 Analyzing with Gemini...")
    result = client.analyze_sensor_data(reading)

    if "error" in result:
        print(f"\n❌ Analysis failed: {result['error']}")
        if args.verbose:
            print(f"Details: {result.get('details', 'No details')}")
        sys.exit(1)

    # Display results
    print("\n" + "="*60)
    print("ELECTROCHEMICAL ANALYSIS RESULTS")
    print("="*60)

    if "text_summary" in result:
        print(f"\n📝 Summary:\n   {result['text_summary']}")

    if "status_band" in result:
        status_icon = {"HEALTHY": "✓", "WARNING": "⚠", "CRITICAL": "🚨"}.get(result["status_band"], "•")
        print(f"\n⚡ Status: {status_icon} {result['status_band']}")

    if "electrochemical_severity_0_to_10" in result:
        severity = result["electrochemical_severity_0_to_10"]
        confidence = result.get("confidence_0_to_1", 0)
        severity_bar = "█" * int(severity) + "░" * (10 - int(severity))
        print(f"\n📊 Severity: {severity_bar} {severity:.1f}/10")
        print(f"   Confidence: {confidence:.0%}")

    if "rp_ohm" in result:
        print(f"\n🔬 Measurements:")
        print(f"   • Polarization Resistance (Rp): {result['rp_ohm']:,.0f} Ω")
        print(f"   • Corrosion Current (Icorr): {result['current_ma']:.3f} mA")

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


if __name__ == "__main__":
    main()
