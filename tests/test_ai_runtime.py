from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai.runtime import AIConfig, load_ai_config


class TestAIRuntime(unittest.TestCase):
    def test_load_ai_config_reads_explicit_vertex_settings(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "settings.yaml").write_text(
                textwrap.dedent(
                    """
                    ai:
                      provider: vertex
                      auth_mode: auto
                      project_id: corrosion-lab
                      location: us-central1
                      primary_model_id: gemini-2.5-flash
                      fallback_model_id: gemini-2.5-pro
                      enable_cloud_vision: true
                      enable_cloud_orchestrator: false
                      browser_timeout_seconds: 25
                      sensor_timeout_seconds: 8
                      vision_timeout_seconds: 10
                      final_report_timeout_seconds: 7
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (root / "config" / "retry_policy.yaml").write_text(
                textwrap.dedent(
                    """
                    retry:
                      ai_call:
                        max_attempts: 2
                        timeout_seconds: 6
                        backoff_seconds: 1
                      ai_circuit_breaker:
                        failures: 4
                        cooldown_seconds: 90
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            config = load_ai_config(root)

        self.assertEqual(
            config,
            AIConfig(
                provider="vertex",
                auth_mode="auto",
                project_id="corrosion-lab",
                location="us-central1",
                primary_model_id="gemini-2.5-flash",
                fallback_model_id="gemini-2.5-pro",
                enable_cloud_vision=True,
                enable_cloud_orchestrator=False,
                browser_timeout_seconds=25.0,
                sensor_timeout_seconds=8.0,
                vision_timeout_seconds=10.0,
                final_report_timeout_seconds=7.0,
                max_attempts=2,
                backoff_seconds=1.0,
                circuit_breaker_failures=4,
                circuit_breaker_cooldown_seconds=90.0,
            ),
        )

    def test_load_ai_config_defaults_to_local_safe_values(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "settings.yaml").write_text("ai: {}\n", encoding="utf-8")
            (root / "config" / "retry_policy.yaml").write_text("retry: {}\n", encoding="utf-8")

            config = load_ai_config(root)

        self.assertEqual(config.auth_mode, "auto")
        self.assertEqual(config.provider, "vertex")
        self.assertEqual(config.location, "global")
        self.assertTrue(config.enable_cloud_vision)
        self.assertTrue(config.enable_cloud_orchestrator)
        self.assertGreater(config.browser_timeout_seconds, config.final_report_timeout_seconds)


if __name__ == "__main__":
    unittest.main()
