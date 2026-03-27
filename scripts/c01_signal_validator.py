#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any


def _read_numeric_csv(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            row: dict[str, float] = {}
            for k, v in raw.items():
                if v is None or v.strip() == "":
                    continue
                row[k.strip()] = float(v)
            if row:
                rows.append(row)
    return rows


def _estimate_freq_zero_crossing(time_s: list[float], sig: list[float]) -> float:
    if len(sig) < 3:
        return 0.0
    mean = statistics.fmean(sig)
    signs = [1 if x >= mean else -1 for x in sig]
    crossings = 0
    for i in range(1, len(signs)):
        if signs[i] != signs[i - 1]:
            crossings += 1
    duration = max(time_s) - min(time_s)
    if duration <= 0:
        return 0.0
    cycles = crossings / 2.0
    return cycles / duration


def validate_waveform(rows: list[dict[str, float]], expected_peak: float, expected_freq: float, amp_tol: float, freq_tol: float) -> dict[str, Any]:
    t = [r["time_s"] for r in rows if "time_s" in r and "voltage_v" in r]
    v = [r["voltage_v"] for r in rows if "time_s" in r and "voltage_v" in r]
    if not t or len(t) != len(v):
        return {"status": "fail", "reason": "missing time_s/voltage_v columns"}

    vpp = max(v) - min(v)
    peak = vpp / 2.0
    offset = statistics.fmean(v)
    freq = _estimate_freq_zero_crossing(t, v)

    moving_avg = []
    window = 5
    for i in range(len(v)):
        start = max(0, i - window + 1)
        moving_avg.append(statistics.fmean(v[start : i + 1]))
    residual = [v[i] - moving_avg[i] for i in range(len(v))]
    noise_std = statistics.pstdev(residual) if len(residual) > 1 else 0.0

    amp_ok = abs(peak - expected_peak) <= (expected_peak * amp_tol)
    freq_ok = abs(freq - expected_freq) <= (expected_freq * freq_tol)

    return {
        "status": "pass" if amp_ok and freq_ok else "fail",
        "metrics": {
            "peak_v": round(peak, 6),
            "vpp_v": round(vpp, 6),
            "offset_v": round(offset, 6),
            "freq_hz": round(freq, 6),
            "noise_std_v": round(noise_std, 6),
        },
        "checks": {
            "amplitude_ok": amp_ok,
            "frequency_ok": freq_ok,
            "expected_peak_v": expected_peak,
            "expected_freq_hz": expected_freq,
        },
    }


def validate_adc(rows: list[dict[str, float]], std_max: float, p2p_max: float, expect_corr: str) -> dict[str, Any]:
    if not rows:
        return {"status": "fail", "reason": "empty adc csv"}

    if "adc_v" not in rows[0]:
        return {"status": "fail", "reason": "missing adc_v column"}

    adc = [r["adc_v"] for r in rows]
    mean = statistics.fmean(adc)
    std = statistics.pstdev(adc) if len(adc) > 1 else 0.0
    p2p = max(adc) - min(adc)

    std_ok = std <= std_max
    p2p_ok = p2p <= p2p_max

    corr_state = "not_checked"
    corr_ok = True
    if "dac_v" in rows[0] and len(rows) > 2:
        dac = [r["dac_v"] for r in rows]
        corr = _pearson(dac, adc)
        corr_state = corr
        if expect_corr == "positive":
            corr_ok = corr > 0
        elif expect_corr == "negative":
            corr_ok = corr < 0

    return {
        "status": "pass" if std_ok and p2p_ok and corr_ok else "fail",
        "metrics": {
            "mean_v": round(mean, 6),
            "std_v": round(std, 6),
            "peak_to_peak_v": round(p2p, 6),
            "correlation": corr_state,
        },
        "checks": {
            "std_ok": std_ok,
            "peak_to_peak_ok": p2p_ok,
            "polarity_ok": corr_ok,
            "std_max_v": std_max,
            "peak_to_peak_max_v": p2p_max,
            "expect_correlation": expect_corr,
        },
    }


def _pearson(a: list[float], b: list[float]) -> float:
    am = statistics.fmean(a)
    bm = statistics.fmean(b)
    num = sum((x - am) * (y - bm) for x, y in zip(a, b))
    den_a = math.sqrt(sum((x - am) ** 2 for x in a))
    den_b = math.sqrt(sum((y - bm) ** 2 for y in b))
    den = den_a * den_b
    if den == 0:
        return 0.0
    return num / den


def main() -> None:
    parser = argparse.ArgumentParser(description="C01 signal sanity validator")
    parser.add_argument("--waveform-csv", type=Path)
    parser.add_argument("--adc-csv", type=Path)
    parser.add_argument("--expected-peak-v", type=float, default=0.01)
    parser.add_argument("--expected-freq-hz", type=float, default=0.1)
    parser.add_argument("--amp-tol", type=float, default=0.2)
    parser.add_argument("--freq-tol", type=float, default=0.1)
    parser.add_argument("--adc-std-max", type=float, default=0.0015)
    parser.add_argument("--adc-p2p-max", type=float, default=0.01)
    parser.add_argument("--expect-correlation", choices=["positive", "negative", "none"], default="none")
    parser.add_argument("--output", type=Path, default=Path("data/sessions/c01/validation-summary.json"))
    args = parser.parse_args()

    results: dict[str, Any] = {"chunk": "C01", "status": "pass", "checks": {}}

    if args.waveform_csv:
        wf_rows = _read_numeric_csv(args.waveform_csv)
        wf_result = validate_waveform(wf_rows, args.expected_peak_v, args.expected_freq_hz, args.amp_tol, args.freq_tol)
        results["checks"]["waveform"] = wf_result
        if wf_result.get("status") != "pass":
            results["status"] = "fail"

    if args.adc_csv:
        adc_rows = _read_numeric_csv(args.adc_csv)
        adc_result = validate_adc(adc_rows, args.adc_std_max, args.adc_p2p_max, args.expect_correlation)
        results["checks"]["adc"] = adc_result
        if adc_result.get("status") != "pass":
            results["status"] = "fail"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))

    if results["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
