from __future__ import annotations

import colorsys
import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

from pydantic import BaseModel, Field
from PIL import Image, ImageFilter, ImageStat
from PIL import ImageChops

from edge.src.logging_setup import configure_logging
import logging
import yaml


class VisionResult(BaseModel):
    timestamp: str
    cycle_id: str
    image_id: str
    roi_info: dict[str, float]
    rust_coverage_pct: float
    rust_coverage_band: str
    pitting_proxy_count: int
    pitting_severity_band: str
    surface_quality_class: str
    dominant_color_class: str
    morphology_class: str
    visual_severity_0_to_10: float
    confidence_0_to_1: float
    key_findings: list[str]
    uncertainty_drivers: list[str]
    quality_flags: list[str]
    degraded_mode: bool
    fallback_reason: str
    capture_metadata: dict[str, Any] = Field(default_factory=dict)
    model_version: str
    preprocessing_version: str


@dataclass
class CameraProfile:
    still_width: int
    still_height: int
    roi_x: float
    roi_y: float
    roi_w: float
    roi_h: float
    exposure_mode: str
    exposure_time_us: int
    analogue_gain: float
    awb_mode: str
    blur_threshold: float
    overexposed_pct_max: float
    underexposed_pct_max: float


class VisionPipeline:
    def __init__(
        self,
        project_root: str | Path,
        model_version: str = "vision-c04-v1",
        preprocessing_version: str = "pre-c04-v1",
        use_mock_camera: bool = True,
    ) -> None:
        self.project_root = Path(project_root)
        self.model_version = model_version
        self.preprocessing_version = preprocessing_version
        self.use_mock_camera = use_mock_camera
        self.profile = self._load_camera_profile()

        self.session_dir = self.project_root / "data" / "sessions" / "c04"
        self.captures_dir = self.session_dir / "captures"
        self.results_dir = self.session_dir / "results"
        self.calib_dir = self.session_dir / "calibration"
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.calib_dir.mkdir(parents=True, exist_ok=True)

        configure_logging(self.project_root / "data" / "logs" / "vision.log")
        self.logger = logging.getLogger("corrosion.vision")
        self.last_valid_result: dict[str, Any] | None = None
        self.last_valid_image: Path | None = None

    def _load_camera_profile(self) -> CameraProfile:
        path = self.project_root / "config" / "camera_profile.yaml"
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        c = cfg["camera"]
        roi = c["roi"]
        awb_raw = c.get("awb_mode", "off")
        if isinstance(awb_raw, bool):
            awb_mode = "auto" if awb_raw else "off"
        else:
            awb_mode = str(awb_raw)

        return CameraProfile(
            still_width=int(c["still_width"]),
            still_height=int(c["still_height"]),
            roi_x=float(roi["x"]),
            roi_y=float(roi["y"]),
            roi_w=float(roi["w"]),
            roi_h=float(roi["h"]),
            exposure_mode=str(c.get("exposure_mode", "manual")),
            exposure_time_us=int(c.get("exposure_time_us", 12000)),
            analogue_gain=float(c.get("analogue_gain", 1.5)),
            awb_mode=awb_mode,
            blur_threshold=float(c.get("blur_threshold", 90.0)),
            overexposed_pct_max=float(c.get("overexposed_pct_max", 4.0)),
            underexposed_pct_max=float(c.get("underexposed_pct_max", 4.0)),
        )

    def calibrate_and_lock_profile(self) -> Path:
        payload = {
            "locked_at": _ts(),
            "still_width": self.profile.still_width,
            "still_height": self.profile.still_height,
            "roi": {
                "x": self.profile.roi_x,
                "y": self.profile.roi_y,
                "w": self.profile.roi_w,
                "h": self.profile.roi_h,
            },
            "exposure_mode": self.profile.exposure_mode,
            "exposure_time_us": self.profile.exposure_time_us,
            "analogue_gain": self.profile.analogue_gain,
            "awb_mode": self.profile.awb_mode,
        }
        out = self.calib_dir / "locked_camera_profile.json"
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.logger.info("camera calibrated", extra={"event": "vision_calibration", "component": "vision"})
        return out

    def run_cycle(
        self,
        cycle_id: str,
        capture_source_image: str | Path | None = None,
        retries: int = 3,
        force_capture_failure: bool = False,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        fallback_reason = ""
        image_path: Path | None = None
        analyzed: dict[str, Any] | None = None
        last_quality_flags: list[str] = []

        for attempt in range(1, retries + 1):
            try:
                if force_capture_failure:
                    raise RuntimeError("forced capture failure for test")
                image_path = self.capture_image(cycle_id, capture_source_image)

                analyzed = self.analyze_image(image_path, cycle_id)
                qf = analyzed.get("quality_flags", [])
                if qf:
                    last_quality_flags = list(qf)
                    self.logger.warning(
                        "quality gate failed, retrying capture",
                        extra={
                            "event": "vision_quality_retry",
                            "component": "vision",
                            "attempt": attempt,
                            "quality_flags": qf,
                        },
                    )
                    time.sleep(0.05)
                    continue

                break
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning(
                    "capture attempt failed",
                    extra={
                        "event": "vision_capture_retry",
                        "component": "vision",
                        "attempt": attempt,
                        "error": str(exc),
                    },
                )
                time.sleep(0.05)

        if analyzed is None or image_path is None:
            fallback_reason = "capture_failed_retries_exhausted"
            quality_flags = ["capture_failed"]
            result = self._fallback_result(cycle_id, quality_flags, fallback_reason)
            result["latency_ms"] = int((time.perf_counter() - start) * 1000)
            self._write_result(cycle_id, result)
            return result

        if analyzed.get("quality_flags", []):
            fallback_reason = "quality_gate_failed_retries_exhausted"
            quality_flags = sorted(set(last_quality_flags or analyzed.get("quality_flags", [])))
            result = self._fallback_result(cycle_id, quality_flags, fallback_reason)
            result["latency_ms"] = int((time.perf_counter() - start) * 1000)
            self._write_result(cycle_id, result)
            return result

        result = analyzed
        result["degraded_mode"] = result.get("degraded_mode", False)
        result["fallback_reason"] = result.get("fallback_reason", "")
        result["latency_ms"] = int((time.perf_counter() - start) * 1000)

        if not result["degraded_mode"]:
            self.last_valid_result = dict(result)
            self.last_valid_image = image_path

        self._write_result(cycle_id, result)
        return result

    def capture_image(self, cycle_id: str, capture_source_image: str | Path | None = None) -> Path:
        out = self.captures_dir / f"{cycle_id}.jpg"

        if self.use_mock_camera:
            if capture_source_image is None:
                raise ValueError("mock camera requires capture_source_image")
            src = Path(capture_source_image)
            shutil.copy2(src, out)
            self._write_capture_metadata(
                cycle_id=cycle_id,
                image_path=out,
                camera_binary="mock-camera",
                source_image=str(src),
            )
            return out

        camera_bin = self._resolve_camera_binary()
        cmd = [
            camera_bin,
            "-n",
            "--width",
            str(self.profile.still_width),
            "--height",
            str(self.profile.still_height),
            "--shutter",
            str(self.profile.exposure_time_us),
            "--gain",
            str(self.profile.analogue_gain),
            "--awb",
            self.profile.awb_mode,
            "-o",
            str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        self._write_capture_metadata(
            cycle_id=cycle_id,
            image_path=out,
            camera_binary=camera_bin,
            source_image=None,
        )
        return out

    def _resolve_camera_binary(self) -> str:
        # Prefer modern Raspberry Pi camera apps naming on newer OS images.
        if shutil.which("rpicam-still"):
            return "rpicam-still"
        if shutil.which("libcamera-still"):
            return "libcamera-still"
        raise RuntimeError("No supported camera binary found. Install rpicam-apps or libcamera-apps.")

    def analyze_image(self, image_path: str | Path, cycle_id: str) -> dict[str, Any]:
        path = Path(image_path)
        img = Image.open(path).convert("RGB")
        roi = self._crop_roi(img)
        capture_metadata = self._read_capture_metadata(cycle_id)

        quality_flags = self._quality_flags(roi)
        if quality_flags:
            return self._empty_result(
                cycle_id=cycle_id,
                quality_flags=quality_flags,
                degraded_mode=False,
                fallback_reason="quality_gate_failed",
                capture_metadata=capture_metadata,
            )

        rust_pct, rust_band = self._rust_coverage(roi)
        pitting_count, pitting_band = self._pitting_proxy(roi)
        dominant_color = self._dominant_color_class(roi)
        morphology = self._morphology_class(roi)
        surface_quality = self._surface_quality_class(roi, rust_pct, pitting_count)

        severity = min(10.0, max(0.0, (rust_pct / 10.0) * 0.65 + min(3.5, pitting_count / 60.0 * 3.5)))
        confidence = self._confidence(roi, quality_flags, rust_pct, pitting_count)
        key_findings = [
            f"rust_coverage={round(rust_pct, 2)}% ({rust_band})",
            f"pitting_proxy_count={int(pitting_count)} ({pitting_band})",
            f"morphology={morphology}, dominant_color={dominant_color}",
        ]
        uncertainty_drivers = self._uncertainty_drivers(confidence, quality_flags, rust_pct, pitting_count)

        payload = VisionResult(
            timestamp=_ts(),
            cycle_id=cycle_id,
            image_id=f"img-{uuid.uuid4().hex[:12]}",
            roi_info={
                "x": self.profile.roi_x,
                "y": self.profile.roi_y,
                "w": self.profile.roi_w,
                "h": self.profile.roi_h,
            },
            rust_coverage_pct=round(rust_pct, 2),
            rust_coverage_band=rust_band,
            pitting_proxy_count=int(pitting_count),
            pitting_severity_band=pitting_band,
            surface_quality_class=surface_quality,
            dominant_color_class=dominant_color,
            morphology_class=morphology,
            visual_severity_0_to_10=round(severity, 2),
            confidence_0_to_1=round(confidence, 3),
            key_findings=key_findings,
            uncertainty_drivers=uncertainty_drivers,
            quality_flags=quality_flags,
            degraded_mode=False,
            fallback_reason="",
            capture_metadata=capture_metadata,
            model_version=self.model_version,
            preprocessing_version=self.preprocessing_version,
        ).model_dump()
        return payload

    def _write_result(self, cycle_id: str, payload: dict[str, Any]) -> None:
        out = self.results_dir / f"{cycle_id}.json"
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.logger.info(
            "vision cycle completed",
            extra={
                "event": "vision_cycle",
                "component": "vision",
                "cycle_id": cycle_id,
                "degraded_mode": payload.get("degraded_mode", False),
                "latency_ms": payload.get("latency_ms", 0),
            },
        )

    def _crop_roi(self, img: Image.Image) -> Image.Image:
        w, h = img.size
        x0 = int(self.profile.roi_x * w)
        y0 = int(self.profile.roi_y * h)
        x1 = int((self.profile.roi_x + self.profile.roi_w) * w)
        y1 = int((self.profile.roi_y + self.profile.roi_h) * h)
        x0 = max(0, min(x0, w - 1))
        y0 = max(0, min(y0, h - 1))
        x1 = max(x0 + 1, min(x1, w))
        y1 = max(y0 + 1, min(y1, h))
        roi = img.crop((x0, y0, x1, y1))
        # Keep compute bounded while preserving deterministic cycle timing.
        return roi.resize((640, 640))

    def _quality_flags(self, roi: Image.Image) -> list[str]:
        flags: list[str] = []
        gray = roi.convert("L")
        # Sharpness proxy: high-frequency residual between source and Gaussian-smoothed copy.
        hf = ImageChops.difference(gray, gray.filter(ImageFilter.GaussianBlur(radius=2.0)))
        blur_score = ImageStat.Stat(hf).mean[0] * 2000.0
        if blur_score < self.profile.blur_threshold:
            flags.append("blur_too_high")

        hist = gray.histogram()
        total = max(1, sum(hist))
        low = sum(hist[:10]) / total * 100.0
        high = sum(hist[246:]) / total * 100.0
        if low > self.profile.underexposed_pct_max:
            flags.append("underexposed")
        if high > self.profile.overexposed_pct_max:
            flags.append("overexposed")
        return flags

    def _rust_coverage(self, roi: Image.Image) -> tuple[float, str]:
        hsv = roi.convert("HSV")
        rust = 0
        total = 0
        for h, s, v in hsv.getdata():
            total += 1
            deg = h * 360.0 / 255.0
            if (8 <= deg <= 38) and s >= 65 and v >= 35:
                rust += 1
        pct = (rust / max(1, total)) * 100.0
        if pct < 5:
            band = "none"
        elif pct < 15:
            band = "light"
        elif pct < 35:
            band = "moderate"
        else:
            band = "heavy"
        return pct, band

    def _pitting_proxy(self, roi: Image.Image) -> tuple[int, str]:
        gray = roi.convert("L")
        med = gray.filter(ImageFilter.MedianFilter(size=3))
        diff = Image.new("L", gray.size)
        g_data = list(gray.getdata())
        m_data = list(med.getdata())
        diff.putdata([abs(a - b) for a, b in zip(g_data, m_data)])

        count = 0
        for g, d in zip(g_data, diff.getdata()):
            if g < 75 and d > 15:
                count += 1

        if count < 400:
            band = "none"
        elif count < 1200:
            band = "low"
        elif count < 2600:
            band = "moderate"
        else:
            band = "high"
        return count, band

    def _dominant_color_class(self, roi: Image.Image) -> str:
        small = roi.resize((64, 64)).convert("RGB")
        hs: list[float] = []
        ss: list[float] = []
        vs: list[float] = []
        for r, g, b in small.getdata():
            h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            hs.append(h * 360.0)
            ss.append(s)
            vs.append(v)
        avg_h = fmean(hs)
        avg_s = fmean(ss)
        avg_v = fmean(vs)

        if avg_s < 0.15 and avg_v > 0.5:
            return "gray_silver"
        if 8 <= avg_h <= 38 and avg_s > 0.2:
            return "brown_orange"
        if avg_v < 0.25:
            return "dark_degraded"
        return "mixed"

    def _morphology_class(self, roi: Image.Image) -> str:
        w, h = roi.size
        rust_cells: list[float] = []
        for gy in range(4):
            for gx in range(4):
                x0 = gx * w // 4
                y0 = gy * h // 4
                x1 = (gx + 1) * w // 4
                y1 = (gy + 1) * h // 4
                cell = roi.crop((x0, y0, x1, y1))
                pct, _ = self._rust_coverage(cell)
                rust_cells.append(pct)
        mean = fmean(rust_cells)
        spread = max(rust_cells) - min(rust_cells)
        if mean < 5:
            return "none"
        if spread > 22:
            return "localized"
        return "uniform"

    def _surface_quality_class(self, roi: Image.Image, rust_pct: float, pitting_count: int) -> str:
        gray = roi.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        texture = ImageStat.Stat(edges).mean[0]
        rough_index = texture + rust_pct * 0.35 + min(60.0, pitting_count / 120.0)
        if rough_index < 18:
            return "smooth"
        if rough_index < 35:
            return "slightly_rough"
        if rough_index < 58:
            return "rough"
        return "heavily_degraded"

    def _confidence(self, roi: Image.Image, quality_flags: list[str], rust_pct: float, pitting_count: int) -> float:
        if quality_flags:
            return 0.3
        gray = roi.convert("L")
        hist = gray.histogram()
        total = max(1, sum(hist))
        mid = sum(hist[40:215]) / total
        signal = min(1.0, (rust_pct / 45.0) + min(0.5, pitting_count / 4000.0))
        return max(0.45, min(0.98, 0.55 + 0.25 * mid + 0.2 * signal))

    def _uncertainty_drivers(
        self,
        confidence: float,
        quality_flags: list[str],
        rust_pct: float,
        pitting_count: int,
    ) -> list[str]:
        drivers: list[str] = []
        if quality_flags:
            drivers.append("quality_flags_present")
        if confidence < 0.65:
            drivers.append("low_model_confidence")
        if rust_pct < 3.0:
            drivers.append("low_rust_signal")
        if pitting_count < 200:
            drivers.append("low_pitting_signal")
        if not drivers:
            drivers.append("none")
        return drivers

    def _capture_metadata_path(self, cycle_id: str) -> Path:
        return self.captures_dir / f"{cycle_id}.meta.json"

    def _write_capture_metadata(
        self,
        cycle_id: str,
        image_path: Path,
        camera_binary: str,
        source_image: str | None,
    ) -> None:
        payload: dict[str, Any] = {
            "timestamp": _ts(),
            "cycle_id": cycle_id,
            "frame_id": f"frame-{uuid.uuid4().hex[:12]}",
            "image_path": str(image_path),
            "image_format": "jpeg",
            "still_width": self.profile.still_width,
            "still_height": self.profile.still_height,
            "roi_id": "default_roi",
            "roi": {
                "x": self.profile.roi_x,
                "y": self.profile.roi_y,
                "w": self.profile.roi_w,
                "h": self.profile.roi_h,
            },
            "exposure_mode": self.profile.exposure_mode,
            "exposure_time_us": self.profile.exposure_time_us,
            "analogue_gain": self.profile.analogue_gain,
            "awb_mode": self.profile.awb_mode,
            "camera_binary": camera_binary,
        }
        if source_image:
            payload["source_image"] = source_image
        self._capture_metadata_path(cycle_id).write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    def _read_capture_metadata(self, cycle_id: str) -> dict[str, Any]:
        p = self._capture_metadata_path(cycle_id)
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))

    def _fallback_result(self, cycle_id: str, quality_flags: list[str], fallback_reason: str) -> dict[str, Any]:
        if self.last_valid_result is not None:
            result = dict(self.last_valid_result)
            result["timestamp"] = _ts()
            result["cycle_id"] = cycle_id
            result["degraded_mode"] = True
            result["fallback_reason"] = fallback_reason
            merged_flags = sorted(set(result.get("quality_flags", []) + quality_flags + ["stale_result"]))
            result["quality_flags"] = merged_flags
            result["uncertainty_drivers"] = sorted(set(result.get("uncertainty_drivers", []) + ["stale_fallback_used"]))
            result["capture_metadata"] = self._read_capture_metadata(cycle_id)
            return result

        return self._empty_result(
            cycle_id=cycle_id,
            quality_flags=quality_flags,
            degraded_mode=True,
            fallback_reason=fallback_reason,
            capture_metadata=self._read_capture_metadata(cycle_id),
        )

    def _empty_result(
        self,
        cycle_id: str,
        quality_flags: list[str],
        degraded_mode: bool,
        fallback_reason: str,
        capture_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        payload = VisionResult(
            timestamp=_ts(),
            cycle_id=cycle_id,
            image_id=f"img-{uuid.uuid4().hex[:12]}",
            roi_info={
                "x": self.profile.roi_x,
                "y": self.profile.roi_y,
                "w": self.profile.roi_w,
                "h": self.profile.roi_h,
            },
            rust_coverage_pct=0.0,
            rust_coverage_band="unknown",
            pitting_proxy_count=0,
            pitting_severity_band="unknown",
            surface_quality_class="unknown",
            dominant_color_class="unknown",
            morphology_class="unknown",
            visual_severity_0_to_10=0.0,
            confidence_0_to_1=0.2,
            key_findings=["no_valid_visual_signal"],
            uncertainty_drivers=["degraded_mode", fallback_reason] if fallback_reason else ["degraded_mode"],
            quality_flags=quality_flags,
            degraded_mode=degraded_mode,
            fallback_reason=fallback_reason,
            capture_metadata=capture_metadata,
            model_version=self.model_version,
            preprocessing_version=self.preprocessing_version,
        ).model_dump()
        return payload


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()
