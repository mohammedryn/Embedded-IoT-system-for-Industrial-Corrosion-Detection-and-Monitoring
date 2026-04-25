from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

try:
    import serial
    from serial import SerialException
except Exception:  # pragma: no cover
    serial = None  # type: ignore[assignment]

    class SerialException(Exception):
        pass


LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_BAUD = 115200


class SerialConnectionError(RuntimeError):
    """Raised when the serial port cannot be opened."""


@dataclass(frozen=True, slots=True)
class SerialFrame:
    seq: int
    timestamp: str
    timestamp_unix: float
    rp_ohm: float
    current_ua: float
    status: str
    asym_percent: float | None
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "timestamp_unix": self.timestamp_unix,
            "rp_ohm": self.rp_ohm,
            "current_ua": self.current_ua,
            "status": self.status,
            "asym_percent": self.asym_percent,
            "raw": self.raw,
        }


def parse_frame_line(line: str) -> dict[str, Any]:
    text = line.strip()
    if not text:
        raise ValueError("empty_line")
    if not text.startswith("FRAME:"):
        raise ValueError("missing_prefix")

    body = text[6:].strip()
    if not body:
        raise ValueError("empty_body")

    fields: dict[str, str] = {}
    for token in body.split(";"):
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            raise ValueError(f"invalid_token:{token}")

        key, value = token.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if not key:
            raise ValueError("empty_key")
        if key in fields:
            raise ValueError(f"duplicate_key:{key}")
        fields[key] = value

    for required_key in ("rp", "i", "status"):
        if required_key not in fields:
            raise ValueError(f"missing_field:{required_key}")

    try:
        rp_ohm = float(fields["rp"])
        current_ua = float(fields["i"])
    except ValueError as exc:
        raise ValueError("invalid_numeric") from exc

    status = fields["status"].upper()
    if not status:
        raise ValueError("empty_status")

    asym_percent: float | None = None
    if "asym" in fields and fields["asym"] != "":
        try:
            asym_percent = float(fields["asym"])
        except ValueError as exc:
            raise ValueError("invalid_asym") from exc

    return {
        "rp_ohm": rp_ohm,
        "current_ua": current_ua,
        "status": status,
        "asym_percent": asym_percent,
    }


class SerialFrameReader:
    def __init__(
        self,
        *,
        port: str = DEFAULT_PORT,
        baud: int = DEFAULT_BAUD,
        max_frames: int = 2000,
        read_timeout_s: float = 1.0,
        reconnect_base_s: float = 1.0,
        reconnect_max_s: float = 8.0,
    ) -> None:
        self._port = port
        self._baud = baud
        self._read_timeout_s = read_timeout_s
        self._reconnect_base_s = reconnect_base_s
        self._reconnect_max_s = reconnect_max_s

        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._stop_event = threading.Event()

        self._thread: threading.Thread | None = None
        self._serial: Any = None
        self._callbacks: list[Callable[[SerialFrame], None]] = []

        self._frames = deque(maxlen=max_frames)
        self._seq = 0

    def register_callback(self, callback: Callable[[SerialFrame], None]) -> None:
        with self._lock:
            self._callbacks.append(callback)

    def connect(self, port: str | None = None, baud: int | None = None) -> None:
        with self._lock:
            if port:
                self._port = port
            if baud is not None:
                self._baud = int(baud)

            if self._thread and self._thread.is_alive():
                return

            self._stop_event.clear()
            try:
                self._serial = self._open_serial(self._port, self._baud)
            except SerialException as exc:
                raise SerialConnectionError(
                    f"failed to open serial port {self._port} at {self._baud}"
                ) from exc

            self._thread = threading.Thread(
                target=self._reader_loop,
                name="teensy-frame-reader",
                daemon=True,
            )
            self._thread.start()

    def disconnect(self) -> None:
        self._stop_event.set()

        with self._lock:
            thread = self._thread
            self._thread = None
            self._close_serial_locked()

        with self._condition:
            self._condition.notify_all()

        if thread and thread.is_alive():
            thread.join(timeout=2.5)

    def is_connected(self) -> bool:
        with self._lock:
            return bool(self._serial and self._serial.is_open)

    def snapshot(self) -> list[SerialFrame]:
        with self._condition:
            return list(self._frames)

    def frames_after(self, last_seq: int) -> list[SerialFrame]:
        with self._condition:
            return [frame for frame in self._frames if frame.seq > last_seq]

    def wait_for_frames_after(self, last_seq: int, timeout_s: float) -> list[SerialFrame]:
        with self._condition:
            ready = [frame for frame in self._frames if frame.seq > last_seq]
            if ready:
                return ready
            self._condition.wait(timeout=timeout_s)
            return [frame for frame in self._frames if frame.seq > last_seq]

    def _open_serial(self, port: str, baud: int):
        if serial is None:
            raise SerialException("pyserial is not installed")

        return serial.Serial(
            port=port,
            baudrate=baud,
            timeout=self._read_timeout_s,
            write_timeout=1.0,
        )

    def _reader_loop(self) -> None:
        reconnect_delay = self._reconnect_base_s

        while not self._stop_event.is_set():
            ser = self._get_serial()

            if ser is None or not ser.is_open:
                try:
                    ser = self._open_serial(self._port, self._baud)
                    with self._lock:
                        self._serial = ser
                    reconnect_delay = self._reconnect_base_s
                except SerialException as exc:
                    LOGGER.warning(
                        "serial_reconnect_failed",
                        extra={
                            "port": self._port,
                            "baud": self._baud,
                            "retry_s": reconnect_delay,
                            "error": str(exc),
                        },
                    )
                    if self._stop_event.wait(reconnect_delay):
                        break
                    reconnect_delay = min(reconnect_delay * 2.0, self._reconnect_max_s)
                    continue

            try:
                raw_bytes = ser.readline()
            except SerialException as exc:
                LOGGER.warning(
                    "serial_read_error",
                    extra={"port": self._port, "error": str(exc)},
                )
                with self._lock:
                    self._close_serial_locked()
                if self._stop_event.wait(reconnect_delay):
                    break
                reconnect_delay = min(reconnect_delay * 2.0, self._reconnect_max_s)
                continue
            except Exception:
                LOGGER.exception("serial_read_unexpected_error")
                if self._stop_event.wait(0.25):
                    break
                continue

            if not raw_bytes:
                continue

            line = raw_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                parsed = parse_frame_line(line)
            except ValueError as exc:
                LOGGER.warning(
                    "serial_parse_error",
                    extra={"line": line, "error": str(exc)},
                )
                continue

            self._append_frame(parsed, raw=line)

    def _append_frame(self, parsed: dict[str, Any], *, raw: str) -> None:
        now = time.time()
        timestamp = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        with self._condition:
            self._seq += 1
            frame = SerialFrame(
                seq=self._seq,
                timestamp=timestamp,
                timestamp_unix=now,
                rp_ohm=float(parsed["rp_ohm"]),
                current_ua=float(parsed["current_ua"]),
                status=str(parsed["status"]),
                asym_percent=(
                    float(parsed["asym_percent"]) if parsed.get("asym_percent") is not None else None
                ),
                raw=raw,
            )
            self._frames.append(frame)
            callbacks = tuple(self._callbacks)
            self._condition.notify_all()

        for callback in callbacks:
            try:
                callback(frame)
            except Exception:
                LOGGER.exception("serial_callback_error")

    def _get_serial(self):
        with self._lock:
            return self._serial

    def _close_serial_locked(self) -> None:
        ser = self._serial
        self._serial = None
        if ser is None:
            return
        try:
            if ser.is_open:
                ser.close()
        except Exception:
            LOGGER.exception("serial_close_error")