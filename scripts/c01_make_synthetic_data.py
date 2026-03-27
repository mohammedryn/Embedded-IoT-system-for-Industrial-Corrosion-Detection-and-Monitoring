#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
from pathlib import Path


def main() -> None:
    out = Path("data/sessions/c01")
    out.mkdir(parents=True, exist_ok=True)

    wf_path = out / "waveform_synthetic.csv"
    adc_baseline_path = out / "adc_baseline_synthetic.csv"
    adc_polarity_path = out / "adc_polarity_synthetic.csv"

    dt = 0.2
    total = 120.0
    freq = 0.1
    amp = 0.01

    with wf_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_s", "voltage_v"])
        t = 0.0
        while t <= total:
            noise = 0.0002 * math.sin(2 * math.pi * 0.9 * t)
            v = amp * math.sin(2 * math.pi * freq * t) + noise
            w.writerow([round(t, 4), round(v, 7)])
            t += dt

    with adc_baseline_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_s", "adc_v"])
        t = 0.0
        while t <= total:
            baseline = 0.0045
            noise = 0.0002 * math.sin(2 * math.pi * 1.4 * t)
            adc_v = baseline + noise
            w.writerow([round(t, 4), round(adc_v, 7)])
            t += dt

    with adc_polarity_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_s", "dac_v", "adc_v"])
        t = 0.0
        while t <= total:
            dac_v = amp * math.sin(2 * math.pi * freq * t)
            noise = 0.0002 * math.sin(2 * math.pi * 1.4 * t)
            adc_v = 0.55 * dac_v + noise
            w.writerow([round(t, 4), round(dac_v, 7), round(adc_v, 7)])
            t += dt

    print(f"Wrote {wf_path}")
    print(f"Wrote {adc_baseline_path}")
    print(f"Wrote {adc_polarity_path}")


if __name__ == "__main__":
    main()
