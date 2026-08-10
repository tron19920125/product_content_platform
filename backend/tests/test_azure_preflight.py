from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from product_content_platform.integrations.azure_preflight import run_preflight
from product_content_platform.settings import Settings


class AzurePreflightTest(unittest.TestCase):
    def _settings(self, root: Path, *, generation: str, qa: str) -> Settings:
        return Settings(
            data_root=root,
            database_path=root / "platform.db",
            asset_root=root / "assets",
            production_root=root / "production",
            export_root=root / "exports",
            generation_mode=generation,
            qa_mode=qa,
        )

    def test_local_mode_skips_all_azure_checks(self) -> None:
        with TemporaryDirectory() as directory:
            result = run_preflight(self._settings(Path(directory), generation="local", qa="local"))

        self.assertEqual(result["status"], "local")
        self.assertTrue(all(item["status"] == "skipped" for item in result["components"]))

    def test_azure_mode_validates_routes_and_acquires_identity_token(self) -> None:
        environment = {
            "AZURE_AUTH_MODE": "default_credential",
            "AZURE_OPENAI_RESOURCE_ENDPOINT": "https://demo.services.ai.azure.com/api/projects/example",
            "AZURE_OPENAI_IMAGE_DEPLOYMENT": "gpt-image-2",
            "AZURE_OPENAI_REVIEW_MODEL": "gpt-5-mini",
            "AZURE_AI_VISION_ENDPOINT": "https://demo.cognitiveservices.azure.com",
        }
        with TemporaryDirectory() as directory, patch.dict(os.environ, environment, clear=True), patch(
            "product_content_platform.integrations.azure_preflight.token_provider_from_env",
            side_effect=lambda **_: lambda: "token",
        ) as provider:
            result = run_preflight(self._settings(Path(directory), generation="azure", qa="azure"))

        self.assertEqual(result["status"], "ready")
        self.assertTrue(all(item["status"] == "ready" for item in result["components"]))
        self.assertEqual(provider.call_count, 3)
        serialized = str(result)
        self.assertNotIn("token", serialized)
        self.assertNotIn("api/projects/example", serialized)

    def test_static_mode_reports_missing_credentials_without_raising(self) -> None:
        environment = {
            "AZURE_AUTH_MODE": "static",
            "AZURE_OPENAI_RESOURCE_ENDPOINT": "https://example.openai.azure.com",
            "AZURE_OPENAI_IMAGE_DEPLOYMENT": "gpt-image-2",
            "AZURE_OPENAI_REVIEW_MODEL": "gpt-5-mini",
            "AZURE_AI_VISION_ENDPOINT": "https://example.cognitiveservices.azure.com",
        }
        with TemporaryDirectory() as directory, patch.dict(os.environ, environment, clear=True):
            result = run_preflight(self._settings(Path(directory), generation="azure", qa="azure"))

        self.assertEqual(result["status"], "error")
        self.assertTrue(all(item["status"] == "error" for item in result["components"]))


if __name__ == "__main__":
    unittest.main()
