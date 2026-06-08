from __future__ import annotations

import unittest

from ai.providers.local import LocalHeuristicProvider
from ai.providers.vertex import VertexAIProvider
from ai.runtime import AIConfig


def _config(**overrides: object) -> AIConfig:
    base = AIConfig(
        provider="vertex",
        auth_mode="disabled",
        project_id="",
        location="global",
        primary_model_id="gemini-2.5-flash",
        fallback_model_id="gemini-2.5-pro",
        enable_cloud_vision=True,
        enable_cloud_orchestrator=True,
        browser_timeout_seconds=25.0,
        sensor_timeout_seconds=8.0,
        vision_timeout_seconds=10.0,
        final_report_timeout_seconds=7.0,
        ai_call_timeout_seconds=8.0,
        max_attempts=2,
        backoff_seconds=1.0,
        circuit_breaker_failures=3,
        circuit_breaker_cooldown_seconds=120.0,
    )
    return AIConfig(**{**base.__dict__, **overrides})


class TestLocalHeuristicProvider(unittest.TestCase):
    def test_describe_runtime_reports_local_heuristic_when_disabled(self) -> None:
        provider = LocalHeuristicProvider(config=_config(auth_mode="disabled"))

        runtime = provider.describe_runtime()

        self.assertEqual(runtime["provider"], "local_heuristic")
        self.assertEqual(runtime["runtime_mode"], "local_heuristic")
        self.assertEqual(runtime["auth_mode"], "disabled")
        self.assertEqual(runtime["auth_source"], "disabled")
        self.assertFalse(runtime["cloud_enabled"])
        self.assertFalse(runtime["circuit_breaker_open"])

    def test_health_check_is_safe_without_cloud(self) -> None:
        provider = LocalHeuristicProvider(config=_config(auth_mode="auto"))

        health = provider.health_check()

        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["provider"], "local_heuristic")
        self.assertEqual(health["runtime_mode"], "local_heuristic")


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestVertexAIProvider(unittest.TestCase):
    def test_auto_mode_prefers_service_account_credentials(self) -> None:
        provider = VertexAIProvider(
            config=_config(auth_mode="auto", project_id="explicit-project", location="us-central1"),
            env={"GOOGLE_APPLICATION_CREDENTIALS": "/tmp/service-account.json"},
            credentials_loader=lambda: (_FakeCredentials(), "adc-project"),
            service_account_loader=lambda path: (_FakeCredentials(), "service-account-project"),
        )

        runtime = provider.describe_runtime()

        self.assertEqual(runtime["provider"], "vertex")
        self.assertEqual(runtime["runtime_mode"], "vertex_expert")
        self.assertEqual(runtime["auth_mode"], "auto")
        self.assertEqual(runtime["auth_source"], "service_account")
        self.assertEqual(runtime["project_id"], "explicit-project")
        self.assertTrue(runtime["cloud_enabled"])

    def test_auto_mode_falls_back_to_adc(self) -> None:
        provider = VertexAIProvider(
            config=_config(auth_mode="auto", location="us-central1"),
            env={},
            credentials_loader=lambda: (_FakeCredentials(), "adc-project"),
        )

        runtime = provider.describe_runtime()

        self.assertEqual(runtime["runtime_mode"], "vertex_expert")
        self.assertEqual(runtime["auth_source"], "adc")
        self.assertEqual(runtime["project_id"], "adc-project")

    def test_no_credentials_returns_local_heuristic_runtime(self) -> None:
        provider = VertexAIProvider(
            config=_config(auth_mode="auto"),
            env={},
            credentials_loader=lambda: (_raise_runtime_error()),
        )

        runtime = provider.describe_runtime()

        self.assertEqual(runtime["runtime_mode"], "local_heuristic")
        self.assertEqual(runtime["auth_source"], "none")
        self.assertFalse(runtime["cloud_enabled"])

    def test_circuit_breaker_opens_and_recovers_after_cooldown(self) -> None:
        clock = FakeClock()
        provider = VertexAIProvider(
            config=_config(auth_mode="adc", circuit_breaker_failures=3, circuit_breaker_cooldown_seconds=30.0),
            env={},
            credentials_loader=lambda: (_FakeCredentials(), "adc-project"),
            clock=clock.time,
        )

        provider.record_failure("quota_exceeded")
        provider.record_failure("quota_exceeded")
        provider.record_failure("quota_exceeded")

        open_runtime = provider.describe_runtime()
        self.assertEqual(open_runtime["runtime_mode"], "local_heuristic")
        self.assertTrue(open_runtime["circuit_breaker_open"])
        self.assertEqual(open_runtime["degraded_reason"], "circuit_breaker_open")

        clock.advance(31.0)
        recovered_runtime = provider.describe_runtime()
        self.assertEqual(recovered_runtime["runtime_mode"], "vertex_expert")
        self.assertFalse(recovered_runtime["circuit_breaker_open"])


class _FakeCredentials:
    pass


def _raise_runtime_error():
    raise RuntimeError("adc unavailable")


if __name__ == "__main__":
    unittest.main()
