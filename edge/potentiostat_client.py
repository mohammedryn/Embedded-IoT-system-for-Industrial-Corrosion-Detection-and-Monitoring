"""Potentiostat (electrochemical sensor) simulation and Vertex analysis client."""
from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.providers.vertex import VertexAIProvider
from ai.runtime import load_ai_config


@dataclass
class SensorReading:
    """Simulated potentiostat measurement."""

    timestamp: str
    cycle_id: str
    current_ma: float
    rp_ohm: float
    temperature_c: float = 25.0


class PotentiostatAnalysis(BaseModel):
    """Structured response from electrochemical cloud analysis."""

    text_summary: str
    electrochemical_severity_0_to_10: float = Field(ge=0, le=10)
    status_band: str = Field(description="HEALTHY|WARNING|CRITICAL")
    confidence_0_to_1: float = Field(ge=0, le=1)
    rp_ohm: float
    current_ma: float
    key_findings: list[str]
    recommendations: list[str]
    model_id: str


class SyntheticSensorGenerator:
    """Generate realistic synthetic potentiostat readings."""

    @staticmethod
    def generate_reading(
        cycle_id: str,
        severity_mode: str = "healthy",
        current_range: tuple[float, float] = (0.15, 0.50),
        rp_range: tuple[float, float] = (30000, 100000),
    ) -> SensorReading:
        timestamp = datetime.now(timezone.utc).isoformat()

        if severity_mode == "healthy":
            rp_ohm = random.uniform(60000, 100000)
            current_ma = random.uniform(0.05, 0.20)
        elif severity_mode == "warning":
            rp_ohm = random.uniform(30000, 60000)
            current_ma = random.uniform(0.20, 0.40)
        elif severity_mode == "critical":
            rp_ohm = random.uniform(10000, 30000)
            current_ma = random.uniform(0.40, 1.00)
        else:
            rp_ohm = random.uniform(*rp_range)
            current_ma = random.uniform(*current_range)

        return SensorReading(
            timestamp=timestamp,
            cycle_id=cycle_id,
            current_ma=round(current_ma, 3),
            rp_ohm=round(rp_ohm, 0),
        )


class PotentiostatGeminiClient:
    """Compatibility wrapper that now uses Vertex AI instead of API-key Gemini."""

    def __init__(
        self,
        api_key: str | None = None,
        model_id: str | None = None,
        fallback_model_id: str | None = None,
        *,
        auth_mode: str | None = None,
        project_id: str | None = None,
        location: str | None = None,
    ) -> None:
        if api_key:
            raise ValueError(
                "API key-based Gemini access is deprecated for this project. "
                "Use Vertex auth via ADC or GOOGLE_APPLICATION_CREDENTIALS."
            )

        config = load_ai_config(PROJECT_ROOT)
        self.config = replace(
            config,
            primary_model_id=model_id or config.primary_model_id,
            fallback_model_id=fallback_model_id or config.fallback_model_id,
            auth_mode=auth_mode or config.auth_mode,
            project_id=project_id if project_id is not None else config.project_id,
            location=location or config.location,
        )
        self.provider = VertexAIProvider(config=self.config)
        self.model_id = self.config.primary_model_id
        self.fallback_model_id = self.config.fallback_model_id

    def analyze_sensor_data(self, sensor_reading: SensorReading) -> dict[str, Any]:
        """Analyze potentiostat sensor data and return structured analysis."""
        runtime = self.provider.describe_runtime()
        if runtime.get("runtime_mode") != "vertex_expert":
            return {
                "error": "Vertex AI unavailable for electrochemical analysis",
                "details": runtime,
            }

        prompt = f"""You are an electrochemical corrosion specialist. Analyze this potentiostat measurement and return STRICT JSON only (no markdown, no prose):

Sensor Data:
- Polarization Resistance (Rp): {sensor_reading.rp_ohm} Ω
- Corrosion Current (Icorr): {sensor_reading.current_ma} mA
- Temperature: {sensor_reading.temperature_c}°C

Return STRICT JSON:
{{
  "text_summary": "Brief assessment of corrosion state",
  "electrochemical_severity_0_to_10": 3.5,
  "status_band": "HEALTHY|WARNING|CRITICAL",
  "confidence_0_to_1": 0.85,
  "rp_ohm": {sensor_reading.rp_ohm},
  "current_ma": {sensor_reading.current_ma},
  "key_findings": ["finding1", "finding2"],
  "recommendations": ["recommendation1"],
  "model_id": "the model id that produced this answer"
}}

Guidelines:
- High Rp (>60kΩ) + Low Icorr (<0.2mA) = HEALTHY, severity ~1-2
- Medium Rp (30-60kΩ) + Medium Icorr (0.2-0.4mA) = WARNING, severity ~5-6
- Low Rp (<30kΩ) + High Icorr (>0.4mA) = CRITICAL, severity ~8-9
- Be specific and quantifiable."""

        response_text = ""
        try:
            response_text = self.provider.generate_structured_text(
                prompt=prompt,
                model_id=self.model_id,
                timeout_seconds=self.config.sensor_timeout_seconds,
            )
            analysis_dict = json.loads(response_text)
            analysis_dict["model_id"] = str(analysis_dict.get("model_id") or self.model_id)
            validated = PotentiostatAnalysis.model_validate(analysis_dict)
            return validated.model_dump()
        except json.JSONDecodeError as exc:
            return {
                "error": "Failed to parse Vertex response as JSON",
                "raw_response": response_text,
                "details": str(exc),
            }
        except Exception as exc:  # pylint: disable=broad-except
            return {
                "error": f"Vertex electrochemical analysis failed: {exc}",
                "details": str(exc),
            }
