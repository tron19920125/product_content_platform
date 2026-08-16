from __future__ import annotations

import base64
import inspect
import json
import os
import tempfile
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from product_content_platform.integrations.azure_credentials import (
    AI_FOUNDRY_SCOPE,
    COGNITIVE_SERVICES_SCOPE,
    AzureCredentialConfigurationError,
    token_scope_for_endpoint,
    token_provider_from_env,
)
from product_content_platform.integrations.azure_image_client import (
    default_edit_endpoint,
    default_generation_endpoint,
    edit_image,
    generate_image,
    normalize_image_endpoint,
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


class _StreamingHttpResponse:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._lines = [
            line
            for event in events
            for line in (
                f"event: {event['type']}\n".encode("utf-8"),
                f"data: {json.dumps(event)}\n".encode("utf-8"),
                b"\n",
            )
        ]

    def __enter__(self) -> _StreamingHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __iter__(self):
        return iter(self._lines)


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

    def test_foundry_project_endpoint_uses_ai_foundry_scope(self) -> None:
        credential = _Credential()
        environment = {"AZURE_AUTH_MODE": "default_credential"}
        endpoint = "https://example.services.ai.azure.com/api/projects/demo"
        with patch.dict(os.environ, environment, clear=False):
            with patch(
                "product_content_platform.integrations.azure_credentials._credential",
                return_value=credential,
            ):
                provider = token_provider_from_env(endpoint=endpoint)

        self.assertIsNotNone(provider)
        self.assertEqual("managed-token", provider())
        self.assertEqual([AI_FOUNDRY_SCOPE], credential.scopes)

    def test_cognitive_and_openai_resource_endpoints_keep_cognitive_scope(self) -> None:
        self.assertEqual(
            COGNITIVE_SERVICES_SCOPE,
            token_scope_for_endpoint("https://example.cognitiveservices.azure.com"),
        )
        self.assertEqual(
            COGNITIVE_SERVICES_SCOPE,
            token_scope_for_endpoint("https://example.openai.azure.com"),
        )

    def test_image_generation_quality_defaults_to_high(self) -> None:
        self.assertEqual("high", inspect.signature(generate_image).parameters["quality"].default)
        self.assertEqual("high", inspect.signature(edit_image).parameters["quality"].default)

    def test_image_generation_size_defaults_to_2048_square(self) -> None:
        self.assertEqual("2048x2048", inspect.signature(generate_image).parameters["size"].default)
        self.assertEqual("2048x2048", inspect.signature(edit_image).parameters["size"].default)

    def test_default_image_endpoints_use_deployment_route(self) -> None:
        self.assertEqual(
            "https://example.openai.azure.com/openai/deployments/image-model/images/generations"
            "?api-version=2025-04-01-preview",
            default_generation_endpoint("https://example.openai.azure.com", "image-model"),
        )
        self.assertEqual(
            "https://example.openai.azure.com/openai/deployments/image-model/images/edits"
            "?api-version=2025-04-01-preview",
            default_edit_endpoint("https://example.openai.azure.com", "image-model"),
        )

    def test_foundry_project_endpoint_resolves_to_account_deployment_route(self) -> None:
        project_endpoint = "https://example.services.ai.azure.com/api/projects/demo"
        self.assertEqual(
            "https://example.services.ai.azure.com/openai/deployments/image-model/images/generations"
            "?api-version=2025-04-01-preview",
            default_generation_endpoint(project_endpoint, "image-model"),
        )
        self.assertEqual(
            "https://example.services.ai.azure.com/openai/deployments/image-model/images/edits"
            "?api-version=2025-04-01-preview",
            default_edit_endpoint(project_endpoint, "image-model"),
        )

    def test_project_v1_image_endpoint_drops_api_version(self) -> None:
        self.assertEqual(
            "https://example.services.ai.azure.com/api/projects/demo/openai/v1/images/generations"
            "?trace=true",
            normalize_image_endpoint(
                "https://example.services.ai.azure.com/api/projects/demo/openai/v1/images/generations"
                "?api-version=preview&trace=true"
            ),
        )

    def test_resource_v1_image_endpoint_keeps_api_version(self) -> None:
        endpoint = (
            "https://example.openai.azure.com/openai/v1/images/generations"
            "?api-version=2025-04-01-preview"
        )
        self.assertEqual(endpoint, normalize_image_endpoint(endpoint))

    def test_legacy_deployment_endpoint_keeps_required_api_version(self) -> None:
        endpoint = (
            "https://example.openai.azure.com/openai/deployments/image-model/images/generations"
            "?api-version=2025-04-01-preview"
        )
        self.assertEqual(endpoint, normalize_image_endpoint(endpoint))

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
                            "https://example.services.ai.azure.com/openai/v1/images/generations"
                        ),
                    )

        request = urlopen.call_args.args[0]
        self.assertEqual(
            "https://example.services.ai.azure.com/openai/v1/images/generations",
            request.full_url,
        )
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual("gpt-image-2-prod", payload["model"])
        self.assertEqual("2048x2048", payload["size"])
        self.assertEqual("high", payload["quality"])
        self.assertEqual("test-key", request.headers["Api-key"])

    def test_streaming_generation_uses_completed_sse_image(self) -> None:
        partial = base64.b64encode(b"partial-image").decode("ascii")
        final = base64.b64encode(b"final-image").decode("ascii")
        response = _StreamingHttpResponse(
            [
                {
                    "type": "image_generation.partial_image",
                    "b64_json": partial,
                    "partial_image_index": 0,
                },
                {
                    "type": "image_generation.completed",
                    "b64_json": final,
                    "created_at": 123,
                    "usage": {"total_tokens": 10},
                },
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {"PCP_IMAGE_STREAMING": "true", "PCP_IMAGE_PARTIAL_IMAGES": "3"},
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=response) as urlopen:
                    result = generate_image(
                        prompt="test",
                        output_dir=Path(directory),
                        api_key="test-key",
                        endpoint="https://example.openai.azure.com/images/generations",
                    )
                    result_bytes = result.image_path.read_bytes()

        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertTrue(payload["stream"])
        self.assertEqual(3, payload["partial_images"])
        self.assertEqual(b"final-image", result_bytes)
        self.assertEqual({"total_tokens": 10}, result.usage)

    def test_generation_retries_transient_connection_errors(self) -> None:
        response = _HttpResponse(
            {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode("ascii")}]}
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"PCP_IMAGE_STREAMING": "false"}, clear=False):
                with patch(
                    "urllib.request.urlopen",
                    side_effect=[urllib.error.URLError("SSL EOF"), response],
                ) as urlopen:
                    with patch("time.sleep"):
                        result = generate_image(
                            prompt="test",
                            output_dir=Path(directory),
                            api_key="test-key",
                            endpoint="https://example.openai.azure.com/images/generations",
                        )
                    result_bytes = result.image_path.read_bytes()

        self.assertEqual(2, urlopen.call_count)
        self.assertEqual(b"image-bytes", result_bytes)

    def test_generation_can_disable_streaming_for_transparent_icon_pack(self) -> None:
        response = _HttpResponse(
            {"data": [{"b64_json": base64.b64encode(b"transparent-icon-pack").decode("ascii")}]}
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"PCP_IMAGE_STREAMING": "true"}, clear=False):
                with patch("urllib.request.urlopen", return_value=response) as urlopen:
                    result = generate_image(
                        prompt="three transparent icons",
                        output_dir=Path(directory),
                        api_key="test-key",
                        endpoint="https://example.openai.azure.com/images/generations",
                        background="transparent",
                        stream=False,
                    )
                    result_bytes = result.image_path.read_bytes()
        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertNotIn("stream", payload)
        self.assertEqual("transparent", payload["background"])
        self.assertEqual(b"transparent-icon-pack", result_bytes)

    def test_gpt_image_2_edit_omits_unsupported_input_fidelity(self) -> None:
        response = _HttpResponse(
            {"data": [{"b64_json": base64.b64encode(b"edited-image").decode("ascii")}]}
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.png"
            reference.write_bytes(b"png-bytes")
            with patch.dict(
                os.environ,
                {"AZURE_OPENAI_IMAGE_DEPLOYMENT": "gpt-image-2"},
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=response) as urlopen:
                    result = edit_image(
                        prompt="edit",
                        reference_image_path=reference,
                        output_dir=root,
                        api_key="test-key",
                        endpoint="https://example.services.ai.azure.com/openai/v1/images/edits",
                        input_fidelity="high",
                    )

        request = urlopen.call_args.args[0]
        self.assertNotIn(b'name="input_fidelity"', request.data)
        self.assertIn(b'name="size"\r\n\r\n2048x2048', request.data)
        self.assertIn(b'name="quality"\r\n\r\nhigh', request.data)
        self.assertNotIn("input_fidelity", result.request)
        self.assertEqual("gpt-image-2", result.request["model"])

    def test_unknown_deployment_retries_once_without_input_fidelity_when_rejected(self) -> None:
        response = _HttpResponse(
            {"data": [{"b64_json": base64.b64encode(b"edited-image").decode("ascii")}]}
        )
        error_payload = json.dumps({
            "error": {
                "message": "The model does not support the input_fidelity parameter.",
                "code": "invalid_input_fidelity_model",
            }
        }).encode("utf-8")
        unsupported = urllib.error.HTTPError(
            "https://example.test/images/edits", 400, "Bad Request", {}, BytesIO(error_payload)
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.png"
            reference.write_bytes(b"png-bytes")
            with patch.dict(
                os.environ,
                {"AZURE_OPENAI_IMAGE_DEPLOYMENT": "custom-image-alias"},
                clear=False,
            ):
                with patch(
                    "urllib.request.urlopen", side_effect=[unsupported, response]
                ) as urlopen:
                    result = edit_image(
                        prompt="edit",
                        reference_image_path=reference,
                        output_dir=root,
                        api_key="test-key",
                        endpoint="https://example.test/images/edits",
                        input_fidelity="high",
                    )

        self.assertEqual(2, urlopen.call_count)
        self.assertIn(b'name="input_fidelity"', urlopen.call_args_list[0].args[0].data)
        self.assertNotIn(b'name="input_fidelity"', urlopen.call_args_list[1].args[0].data)
        self.assertNotIn("input_fidelity", result.request)


if __name__ == "__main__":
    unittest.main()
