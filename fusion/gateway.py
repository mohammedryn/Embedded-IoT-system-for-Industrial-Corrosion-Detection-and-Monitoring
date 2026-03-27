from __future__ import annotations

from typing import Any

from fusion.specialists import SensorSpecialistResponse, VisionSpecialistResponse


def validate_before_fusion(*, sensor_payload: dict[str, Any], vision_payload: dict[str, Any]) -> dict[str, Any]:
    """Enforce strict schema validation at the fusion boundary."""
    validated_sensor = SensorSpecialistResponse.model_validate(sensor_payload).model_dump()
    validated_vision = VisionSpecialistResponse.model_validate(vision_payload).model_dump()
    return {
        "sensor": validated_sensor,
        "vision": validated_vision,
    }
