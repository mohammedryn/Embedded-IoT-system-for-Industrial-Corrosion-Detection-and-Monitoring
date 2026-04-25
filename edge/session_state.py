from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Mapping


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        payload = value.to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    raise TypeError(f"Unsupported reading type: {type(value)!r}")


@dataclass(frozen=True, slots=True)
class SessionPhoto:
    id: str
    path: str
    captured_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "captured_at": self.captured_at,
        }


class SessionStateManager:
    def __init__(self, *, max_readings: int = 1000) -> None:
        if max_readings <= 0:
            raise ValueError("max_readings must be > 0")
        self._max_readings = max_readings
        self._lock = threading.RLock()

        self._session_id = ""
        self._created_at = 0.0
        self._photos: list[SessionPhoto] = []
        self._readings = deque(maxlen=self._max_readings)

        self.new_session()

    @property
    def session_id(self) -> str:
        with self._lock:
            return self._session_id

    @property
    def created_at(self) -> float:
        with self._lock:
            return self._created_at

    def new_session(self) -> str:
        with self._lock:
            self._session_id = uuid.uuid4().hex
            self._created_at = time.time()
            self._photos = []
            self._readings = deque(maxlen=self._max_readings)
            return self._session_id

    def add_photo(self, path: str) -> dict[str, Any]:
        photo = SessionPhoto(
            id=uuid.uuid4().hex,
            path=path,
            captured_at=time.time(),
        )
        with self._lock:
            self._photos.append(photo)
        return photo.to_dict()

    def remove_photo(self, photo_id: str) -> bool:
        with self._lock:
            for index, photo in enumerate(self._photos):
                if photo.id == photo_id:
                    self._photos.pop(index)
                    return True
        return False

    def list_photos(self) -> list[dict[str, Any]]:
        with self._lock:
            return [photo.to_dict() for photo in self._photos]

    def add_reading(self, reading: Any) -> dict[str, Any]:
        payload = _as_dict(reading)
        payload.setdefault("ingested_at", time.time())
        with self._lock:
            self._readings.append(payload)
        return dict(payload)

    def latest_reading(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._readings:
                return None
            return dict(self._readings[-1])

    def readings_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._readings]


session_state = SessionStateManager()