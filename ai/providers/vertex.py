from __future__ import annotations

import concurrent.futures
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ai.runtime import AIConfig


@dataclass(frozen=True)
class ResolvedAuth:
    source: str
    credentials: Any | None
    project_id: str
    cloud_enabled: bool
    error: str = ""


class VertexAIProvider:
    """Vertex-backed provider with explicit auth resolution and breaker state."""

    def __init__(
        self,
        *,
        config: AIConfig,
        env: Mapping[str, str] | None = None,
        credentials_loader: Callable[[], tuple[Any, str | None]] | None = None,
        service_account_loader: Callable[[str], tuple[Any, str | None]] | None = None,
        client_factory: Callable[[str, str, Any | None], Any] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self.env = dict(os.environ if env is None else env)
        self.credentials_loader = credentials_loader or self._default_credentials_loader
        self.service_account_loader = service_account_loader or self._default_service_account_loader
        self.client_factory = client_factory or self._default_client_factory
        self.clock = clock or time.time
        self._resolved_auth: ResolvedAuth | None = None
        self._client: Any | None = None
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0
        self._last_failure_reason = ""

    def generate_structured_text(self, *, prompt: str, model_id: str, timeout_seconds: float) -> str:
        return self._generate_content(
            model_id=model_id,
            timeout_seconds=timeout_seconds,
            contents=prompt,
        )

    def analyze_image_with_context(
        self,
        *,
        image_path: str | Path,
        prompt: str,
        model_id: str,
        timeout_seconds: float,
    ) -> str:
        from google.genai import types

        path = Path(image_path)
        image_bytes = path.read_bytes()
        part = types.Part.from_bytes(data=image_bytes, mime_type=self._mime_type_for_path(path))
        return self._generate_content(
            model_id=model_id,
            timeout_seconds=timeout_seconds,
            contents=[prompt, part],
        )

    def health_check(self) -> dict[str, Any]:
        runtime = self.describe_runtime()
        return {
            "status": "ok" if runtime["runtime_mode"] == "vertex_expert" else "degraded",
            "provider": runtime["provider"],
            "runtime_mode": runtime["runtime_mode"],
            "auth_source": runtime["auth_source"],
            "cloud_enabled": runtime["cloud_enabled"],
            "circuit_breaker_open": runtime["circuit_breaker_open"],
        }

    def describe_runtime(self) -> dict[str, Any]:
        auth = self._get_resolved_auth()
        breaker_open = self._is_breaker_open()
        runtime_mode = "vertex_expert"
        degraded_reason = ""
        if breaker_open:
            runtime_mode = "local_heuristic"
            degraded_reason = "circuit_breaker_open"
        elif not auth.cloud_enabled:
            runtime_mode = "local_heuristic"
            degraded_reason = auth.error or "cloud_unavailable"

        return {
            "provider": "vertex",
            "runtime_mode": runtime_mode,
            "auth_mode": self.config.auth_mode,
            "auth_source": auth.source,
            "project_id": auth.project_id,
            "location": self.config.location,
            "cloud_enabled": auth.cloud_enabled and not breaker_open,
            "circuit_breaker_open": breaker_open,
            "degraded_reason": degraded_reason,
            "primary_model_id": self.config.primary_model_id,
            "fallback_model_id": self.config.fallback_model_id,
        }

    def record_failure(self, reason: str) -> None:
        self._last_failure_reason = reason
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.config.circuit_breaker_failures:
            self._breaker_open_until = self.clock() + self.config.circuit_breaker_cooldown_seconds

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0
        self._last_failure_reason = ""

    def _generate_content(self, *, model_id: str, timeout_seconds: float, contents: Any) -> str:
        runtime = self.describe_runtime()
        if runtime["runtime_mode"] != "vertex_expert":
            raise RuntimeError(runtime["degraded_reason"] or "cloud_unavailable")

        try:
            response = self._run_with_timeout(
                lambda: self._get_client().models.generate_content(model=model_id, contents=contents),
                timeout_seconds=timeout_seconds,
            )
            text = getattr(response, "text", "") or ""
            if not text.strip():
                raise ValueError("empty_model_response")
            self.record_success()
            return text
        except Exception as exc:  # pylint: disable=broad-except
            self.record_failure(self._classify_error(exc))
            raise

    def _get_client(self) -> Any:
        if self._client is None:
            auth = self._get_resolved_auth()
            if not auth.cloud_enabled:
                raise RuntimeError(auth.error or "cloud_unavailable")
            self._client = self.client_factory(auth.project_id, self.config.location, auth.credentials)
        return self._client

    def _get_resolved_auth(self) -> ResolvedAuth:
        if self._resolved_auth is None:
            self._resolved_auth = self._resolve_auth()
        return self._resolved_auth

    def _resolve_auth(self) -> ResolvedAuth:
        mode = self.config.auth_mode
        if mode == "disabled":
            return ResolvedAuth(
                source="disabled",
                credentials=None,
                project_id=self.config.project_id,
                cloud_enabled=False,
                error="cloud_disabled",
            )

        service_account_path = self.env.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if mode in {"auto", "service_account"} and service_account_path:
            try:
                credentials, discovered_project = self.service_account_loader(service_account_path)
                return ResolvedAuth(
                    source="service_account",
                    credentials=credentials,
                    project_id=self.config.project_id or (discovered_project or ""),
                    cloud_enabled=True,
                )
            except Exception as exc:  # pylint: disable=broad-except
                if mode == "service_account":
                    return ResolvedAuth(
                        source="service_account",
                        credentials=None,
                        project_id=self.config.project_id,
                        cloud_enabled=False,
                        error=f"service_account_error:{type(exc).__name__}",
                    )

        if mode in {"auto", "adc"}:
            try:
                credentials, discovered_project = self.credentials_loader()
                return ResolvedAuth(
                    source="adc",
                    credentials=credentials,
                    project_id=self.config.project_id or (discovered_project or ""),
                    cloud_enabled=True,
                )
            except Exception as exc:  # pylint: disable=broad-except
                return ResolvedAuth(
                    source="none" if mode == "auto" else "adc",
                    credentials=None,
                    project_id=self.config.project_id,
                    cloud_enabled=False,
                    error=f"adc_error:{type(exc).__name__}",
                )

        return ResolvedAuth(
            source="none",
            credentials=None,
            project_id=self.config.project_id,
            cloud_enabled=False,
            error="cloud_unavailable",
        )

    def _is_breaker_open(self) -> bool:
        if self._breaker_open_until and self.clock() >= self._breaker_open_until:
            self.record_success()
            return False
        return self._breaker_open_until > self.clock()

    @staticmethod
    def _run_with_timeout(fn: Callable[[], Any], *, timeout_seconds: float) -> Any:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(fn)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"vertex call exceeded {timeout_seconds}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _classify_error(exc: Exception) -> str:
        text = str(exc).lower()
        if "timeout" in text:
            return "timeout"
        if "quota" in text or "resource exhausted" in text:
            return "quota_exceeded"
        if "permission" in text or "forbidden" in text or "unauthorized" in text:
            return "permission_denied"
        if "network" in text or "connection" in text or "dns" in text:
            return "network_error"
        if "empty_model_response" in text or "json" in text or "schema" in text:
            return "invalid_model_output"
        return "provider_error"

    @staticmethod
    def _mime_type_for_path(path: Path) -> str:
        suffix = path.suffix.lower()
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(suffix, "image/jpeg")

    @staticmethod
    def _default_credentials_loader() -> tuple[Any, str | None]:
        import google.auth

        return google.auth.default()

    @staticmethod
    def _default_service_account_loader(path: str) -> tuple[Any, str | None]:
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(path)
        return credentials, getattr(credentials, "project_id", None)

    @staticmethod
    def _default_client_factory(project_id: str, location: str, credentials: Any | None) -> Any:
        from google import genai

        return genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
            credentials=credentials,
        )
