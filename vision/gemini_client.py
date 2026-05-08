"""Vertex-backed vision API client with a compatibility surface for legacy helpers."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.providers.vertex import VertexAIProvider
from ai.runtime import load_ai_config


class GeminiAnalysis(BaseModel):
    """Structured response from cloud vision analysis."""

    text_summary: str
    rust_coverage_estimate: str = Field(description="light/moderate/heavy")
    surface_condition: str = Field(description="e.g., uniform, pitted, localized")
    severity_0_to_10: float = Field(ge=0, le=10)
    confidence_0_to_1: float = Field(ge=0, le=1)
    pitting_observed: bool = False
    pitting_evidence: str = "not_observed"
    suspected_damage_modes: list[str] = Field(default_factory=list)
    suspicious_regions: list[str] = Field(default_factory=list)
    corrosion_spot_count_estimate: str = "unknown"
    surface_limitations: list[str] = Field(default_factory=list)
    key_findings: list[str]
    recommendations: list[str]
    model_id: str


class GeminiVisionClient:
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

    def _build_prompt(self, context: dict[str, Any] | None = None) -> str:
        context_json = json.dumps(context or {}, indent=2, sort_keys=True)
        return f"""You are a corrosion-vision specialist reviewing a steel or stainless-steel surface image.
Return STRICT JSON only (no markdown, no prose, no code fences).

Use cautious electrochemical/corrosion language:
- Do not claim exact pit depth, exact alloy grade, or exact corrosion rate from vision alone.
- If the image quality is limited, say so in surface_limitations.
- Differentiate uniform discoloration, runoff staining, isolated spot defects, crevice-like edge attack, and pitting suspicion.
- If the provided context says the sample is in chloride-service/LPR testing, consider that localized attack can exist even when broad rust coverage is low.

Return exactly this schema:
{{
  "text_summary": "2-4 sentence technical description of what the surface visually suggests",
  "rust_coverage_estimate": "none|light|moderate|heavy",
  "surface_condition": "uniform|pitted|localized|mixed|other",
  "severity_0_to_10": 3.5,
  "confidence_0_to_1": 0.85,
  "pitting_observed": false,
  "pitting_evidence": "brief explanation",
  "suspected_damage_modes": ["mode1", "mode2"],
  "suspicious_regions": ["region1", "region2"],
  "corrosion_spot_count_estimate": "none|few|several|many|unknown",
  "surface_limitations": ["limitation1"],
  "key_findings": ["finding1", "finding2", "finding3"],
  "recommendations": ["recommendation1", "recommendation2"],
  "model_id": "the model id that produced this answer"
}}

Context JSON:
{context_json}
"""

    def analyze_image_file(self, image_path: str | Path, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Analyze a single image file and return structured analysis."""
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        runtime = self.provider.describe_runtime()
        if runtime.get("runtime_mode") != "vertex_expert":
            return {
                "error": "Vertex AI unavailable for vision analysis",
                "details": runtime,
            }

        response_text = ""
        try:
            response_text = self.provider.analyze_image_with_context(
                image_path=image_path,
                prompt=self._build_prompt(context),
                model_id=self.model_id,
                timeout_seconds=self.config.vision_timeout_seconds,
            )
            analysis_dict = json.loads(response_text)
            analysis_dict["model_id"] = str(analysis_dict.get("model_id") or self.model_id)
            validated = GeminiAnalysis.model_validate(analysis_dict)
            return validated.model_dump()
        except json.JSONDecodeError as exc:
            return {
                "error": "Failed to parse Vertex response as JSON",
                "raw_response": response_text,
                "details": str(exc),
            }
        except Exception as exc:  # pylint: disable=broad-except
            return {
                "error": f"Vertex vision analysis failed: {exc}",
                "details": str(exc),
            }

    def analyze_image_bytes(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Analyze image bytes by writing a temporary file and reusing the file path flow."""
        import tempfile

        suffix = {
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }.get(mime_type, ".jpg")

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(image_bytes)
            temp_path = Path(handle.name)

        try:
            return self.analyze_image_file(temp_path, context=context)
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass
