"""Gemini vision API client for image analysis."""
from __future__ import annotations

import base64
import json
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
    """Client for Gemini 2.0 Flash vision analysis."""

    def __init__(self, api_key: str | None = None):
        """Initialize with optional API key. Falls back to GOOGLE_API_KEY env var."""
        import os
        import google.generativeai as genai

        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GOOGLE_API_KEY not provided. Must set via:\n"
                "  export GOOGLE_API_KEY='your-key-here'\n"
                "or pass api_key parameter"
            )
        
        genai.configure(api_key=self.api_key)
        self.client = genai.GenerativeAI()

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
  "model_id": "gemini-2.0-flash"
}

Be specific and quantifiable."""

        # Call Gemini API
        try:
            model = genai.GenerativeModel("gemini-2.0-flash")
            
            # Send image with prompt
            image_part = {
                "mime_type": mime_type,
                "data": image_data
            }
            
            response = model.generate_content([prompt, image_part])
            response_text = response.text.strip()
            
            # Extract JSON from response
            if response_text.startswith("```"):
                # Remove markdown code blocks if present
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            analysis_dict = json.loads(response_text)
            
            # Validate with Pydantic
            validated = GeminiAnalysis.model_validate(analysis_dict)
            return validated.model_dump()
            
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
  "model_id": "gemini-2.0-flash"
}"""

        try:
            model = genai.GenerativeModel("gemini-2.0-flash")
            
            image_part = {
                "mime_type": mime_type,
                "data": image_data
            }
            
            response = model.generate_content([prompt, image_part])
            response_text = response.text.strip()
            
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            analysis_dict = json.loads(response_text)
            validated = GeminiAnalysis.model_validate(analysis_dict)
            return validated.model_dump()
            
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
