"""Gemini vision API client for image analysis."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class GeminiAnalysis(BaseModel):
    """Structured response from Gemini vision analysis."""
    text_summary: str
    rust_coverage_estimate: str = Field(description="light/moderate/heavy")
    surface_condition: str = Field(description="e.g., uniform, pitted, localized")
    severity_0_to_10: float = Field(ge=0, le=10)
    confidence_0_to_1: float = Field(ge=0, le=1)
    key_findings: list[str]
    recommendations: list[str]
    model_id: str


class GeminiVisionClient:
    """Client for Gemini vision analysis."""

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

    def analyze_image_file(self, image_path: str | Path) -> dict[str, Any]:
        """Analyze a single image file and return structured analysis."""
        import google.generativeai as genai

        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Load and encode image
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        # Determine MIME type
        suffix = image_path.suffix.lower()
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp"
        }
        mime_type = mime_types.get(suffix, "image/jpeg")

        # Build the analysis prompt
        prompt = """Analyze this image for corrosion/rust conditions. Return STRICT JSON only (no markdown, no prose):

{
  "text_summary": "Brief description of surface condition",
  "rust_coverage_estimate": "light|moderate|heavy",
  "surface_condition": "uniform|pitted|localized|other",
  "severity_0_to_10": 3.5,
  "confidence_0_to_1": 0.85,
  "key_findings": ["finding1", "finding2"],
  "recommendations": ["recommendation1", "recommendation2"],
  "model_id": "the model id that produced this answer"
}

Be specific and quantifiable."""

        # Call Gemini API with primary model and fallback model.
        response_text = ""
        last_error = ""
        try:
            for model_id in self._models_to_try():
                try:
                    model = genai.GenerativeModel(model_id)

                    image_part = {"mime_type": mime_type, "data": image_data}
                    response = model.generate_content([prompt, image_part])
                    response_text = self._strip_json_fence(response.text)
                    analysis_dict = json.loads(response_text)

                    # Ensure output model_id reflects the actual model used.
                    analysis_dict["model_id"] = model_id
                    validated = GeminiAnalysis.model_validate(analysis_dict)
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
                "details": str(e)
            }
        except Exception as e:
            return {
                "error": f"Gemini API call failed: {str(e)}",
                "details": str(e)
            }

    def analyze_image_bytes(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
        """Analyze image from bytes and return structured analysis."""
        import google.generativeai as genai

        image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

        prompt = """Analyze this image for corrosion/rust conditions. Return STRICT JSON only:

{
  "text_summary": "Brief description",
  "rust_coverage_estimate": "light|moderate|heavy",
  "surface_condition": "uniform|pitted|localized|other",
  "severity_0_to_10": 3.5,
  "confidence_0_to_1": 0.85,
  "key_findings": ["finding1"],
  "recommendations": ["rec1"],
  "model_id": "the model id that produced this answer"
}"""

        response_text = ""
        last_error = ""
        try:
            for model_id in self._models_to_try():
                try:
                    model = genai.GenerativeModel(model_id)
                    image_part = {"mime_type": mime_type, "data": image_data}

                    response = model.generate_content([prompt, image_part])
                    response_text = self._strip_json_fence(response.text)
                    analysis_dict = json.loads(response_text)
                    analysis_dict["model_id"] = model_id
                    validated = GeminiAnalysis.model_validate(analysis_dict)
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
                "details": str(e)
            }
        except Exception as e:
            return {
                "error": f"Gemini API call failed: {str(e)}",
                "details": str(e)
            }
