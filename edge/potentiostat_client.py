"""Potentiostat (electrochemical sensor) simulation and Gemini analysis client."""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class SensorReading:
    """Simulated potentiostat measurement."""
    timestamp: str
    cycle_id: str
    current_ma: float
    rp_ohm: float
    temperature_c: float = 25.0


class PotentiostatAnalysis(BaseModel):
    """Structured response from Gemini electrochemical analysis."""
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
        """
        Generate a synthetic sensor reading.
        
        severity_mode: 'healthy' (high rp, low current), 'warning', 'critical'
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        if severity_mode == "healthy":
            # High polarization resistance, low current
            rp_ohm = random.uniform(60000, 100000)
            current_ma = random.uniform(0.05, 0.20)
        elif severity_mode == "warning":
            # Medium polarization resistance, medium current
            rp_ohm = random.uniform(30000, 60000)
            current_ma = random.uniform(0.20, 0.40)
        elif severity_mode == "critical":
            # Low polarization resistance, high current
            rp_ohm = random.uniform(10000, 30000)
            current_ma = random.uniform(0.40, 1.00)
        else:
            # Random within specified ranges
            rp_ohm = random.uniform(*rp_range)
            current_ma = random.uniform(*current_range)

        return SensorReading(
            timestamp=timestamp,
            cycle_id=cycle_id,
            current_ma=round(current_ma, 3),
            rp_ohm=round(rp_ohm, 0),
        )


class PotentiostatGeminiClient:
    """Client for Gemini electrochemical analysis."""

    def __init__(
        self,
        api_key: str | None = None,
        model_id: str | None = None,
        fallback_model_id: str | None = None,
    ):
        """Initialize with optional API key. Falls back to GOOGLE_API_KEY env var."""
        import google.generativeai as genai

        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GOOGLE_API_KEY not provided. Must set via:\n"
                "  export GOOGLE_API_KEY='your-key-here'\n"
                "or pass api_key parameter"
            )

        self.model_id = model_id or os.getenv("GEMINI_MODEL_ID") or "gemini-3-flash-preview"
        self.fallback_model_id = fallback_model_id or os.getenv("GEMINI_FALLBACK_MODEL_ID") or "gemini-3.1-pro-preview"

        genai.configure(api_key=self.api_key)

    @staticmethod
    def _strip_json_fence(response_text: str) -> str:
        txt = response_text.strip()
        if txt.startswith("```"):
            parts = txt.split("```")
            if len(parts) >= 2:
                txt = parts[1]
            if txt.startswith("json"):
                txt = txt[4:]
            txt = txt.strip()
        return txt

    def _models_to_try(self) -> list[str]:
        models: list[str] = [self.model_id]
        if self.fallback_model_id and self.fallback_model_id not in models:
            models.append(self.fallback_model_id)
        return models

    def analyze_sensor_data(self, sensor_reading: SensorReading) -> dict[str, Any]:
        """Analyze potentiostat sensor data and return structured analysis."""
        import google.generativeai as genai

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
        last_error = ""
        try:
            for model_id in self._models_to_try():
                try:
                    model = genai.GenerativeModel(model_id)
                    response = model.generate_content(prompt)
                    response_text = self._strip_json_fence(response.text)
                    analysis_dict = json.loads(response_text)

                    # Ensure output model_id reflects actual model used
                    analysis_dict["model_id"] = model_id
                    validated = PotentiostatAnalysis.model_validate(analysis_dict)
                    return validated.model_dump()
                except Exception as e:
                    last_error = f"{model_id}: {e}"
                    continue

            return {
                "error": "Gemini API call failed for all configured models",
                "details": last_error or "No model attempts were made",
            }

        except json.JSONDecodeError as e:
            return {
                "error": "Failed to parse Gemini response as JSON",
                "raw_response": response_text,
                "details": str(e),
            }
        except Exception as e:
            return {
                "error": f"Gemini API call failed: {str(e)}",
                "details": str(e),
            }
