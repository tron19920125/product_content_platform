from __future__ import annotations

import base64
import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from product_content_platform.integrations.azure_credentials import (
    COGNITIVE_SERVICES_SCOPE,
    AzureCredentialConfigurationError,
    token_provider_from_env,
)
from product_content_platform.integrations.azure_image_client import (
    default_edit_endpoint,
    default_generation_endpoint,
    edit_image,
    generate_image,
)


class _AccessToken:
    token = "managed-token"


class _Credential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, scope: str) -> _AccessToken:
        self.scopes.append(scope)
        return _AccessToken()


class _HttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _HttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class AzureCredentialTest(unittest.TestCase):
    def test_static_mode_does_not_construct_azure_credential(self) -> None:
        with patch.dict(os.environ, {"AZURE_AUTH_MODE": "static"}, clear=False):
            self.assertIsNone(token_provider_from_env())

    def test_managed_identity_provider_uses_configured_client_id_and_scope(self) -> None:
        credential = _Credential()
        environment = {
            "AZURE_AUTH_MODE": "managed_identity",
            "AZURE_MANAGED_IDENTITY_CLIENT_ID": "identity-client-id",
        }
        with patch.dict(os.environ, environment, clear=False):
            with patch(
                "product_content_platform.integrations.azure_credentials._credential",
                return_value=credential,
            ) as credential_factory:
                provider = token_provider_from_env()

        self.assertIsNotNone(provider)
        self.assertEqual("managed-token", provider())
        credential_factory.assert_called_once_with("managed_identity", "identity-client-id")
        self.assertEqual([COGNITIVE_SERVICES_SCOPE], credential.scopes)

    def test_invalid_auth_mode_fails_with_clear_error(self) -> None:
        with patch.dict(os.environ, {"AZURE_AUTH_MODE": "unknown"}, clear=False):
            with self.assertRaises(AzureCredentialConfigurationError):
                token_provider_from_env()

    def test_image_generation_quality_defaults_to_high(self) -> None:
        self.assertEqual("high", inspect.signature(generate_image).parameters["quality"].default)
        self.assertEqual("high", inspect.signature(edit_image).parameters["quality"].default)

    def test_image_generation_size_defaults_to_2048_square(self) -> None:
        self.assertEqual("2048x2048", inspect.signature(generate_image).parameters["size"].default)
        self.assertEqual("2048x2048", inspect.signature(edit_image).parameters["size"].default)

    def test_default_image_endpoints_use_azure_openai_v1(self) -> None:
        self.assertEqual(
            "https://example.openai.azure.com/openai/v1/images/generations?api-version=preview",
            default_generation_endpoint("https://example.openai.azure.com", "image-model"),
        )
        self.assertEqual(
            "https://example.openai.azure.com/openai/v1/images/edits?api-version=preview",
            default_edit_endpoint("https://example.openai.azure.com", "image-model"),
        )

    def test_v1_generation_sends_deployment_and_2048_size(self) -> None:
        response = _HttpResponse(
            {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode("ascii")}]}
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {"AZURE_OPENAI_IMAGE_DEPLOYMENT": "gpt-image-2-prod"},
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=response) as urlopen:
                    generate_image(
                        prompt="test",
                        output_dir=Path(directory),
                        api_key="test-key",
                        endpoint=(
                            "https://example.openai.azure.com/openai/v1/images/generations"
                            "?api-version=preview"
                        ),
                    )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual("gpt-image-2-prod", payload["model"])
        self.assertEqual("2048x2048", payload["size"])
        self.assertEqual("high", payload["quality"])
        self.assertEqual("test-key", request.headers["Api-key"])


if __name__ == "__main__":
    unittest.main()
