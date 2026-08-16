from __future__ import annotations

import base64
import http.client
import json
import mimetypes
import os
import random
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


DEFAULT_RESOURCE_ENDPOINT = ""
DEFAULT_DEPLOYMENT = ""
DEFAULT_API_VERSION = "2025-04-01-preview"
DEFAULT_EDIT_API_VERSION = "2025-04-01-preview"
DEFAULT_IMAGE_TIMEOUT_SECONDS = 420
IMAGE_REQUEST_MAX_ATTEMPTS = 4
IMAGE_REQUEST_RETRY_DELAYS = (1.0, 2.0, 4.0)
IMAGE_REQUEST_MAX_RETRY_AFTER_SECONDS = 180.0
RETRYABLE_IMAGE_HTTP_STATUS = {408, 429, 500, 502, 503, 504}
TRANSIENT_IMAGE_ERRORS = (
    http.client.IncompleteRead,
    http.client.RemoteDisconnected,
    socket.timeout,
    TimeoutError,
    ConnectionError,
    ssl.SSLError,
    urllib.error.URLError,
)
_IMAGE_REQUEST_LOCK = threading.Lock()
_INPUT_FIDELITY_UNSUPPORTED_TARGETS: set[str] = set()
TokenProvider = Callable[[], str]


class AzureImageGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedImage:
    image_path: Path
    metadata_path: Path | None
    elapsed_seconds: float
    usage: dict[str, Any]
    response: dict[str, Any]
    request: dict[str, Any] = field(default_factory=dict)


def default_generation_endpoint(
    resource_endpoint: str | None = None,
    deployment: str | None = None,
    api_version: str | None = None,
) -> str:
    resolved_resource = resource_endpoint or os.environ.get("AZURE_OPENAI_RESOURCE_ENDPOINT", "")
    resolved_deployment = deployment or os.environ.get("AZURE_OPENAI_IMAGE_DEPLOYMENT", "")
    resolved_api_version = api_version or os.environ.get("AZURE_OPENAI_IMAGE_API_VERSION", DEFAULT_API_VERSION)
    if not resolved_resource or not resolved_deployment:
        raise AzureImageGenerationError(
            "Set AZURE_OPENAI_IMAGE_ENDPOINT, or configure both "
            "AZURE_OPENAI_RESOURCE_ENDPOINT and AZURE_OPENAI_IMAGE_DEPLOYMENT."
        )
    base = image_resource_endpoint(resolved_resource)
    deployment_path = urllib.parse.quote(resolved_deployment, safe="")
    return (
        f"{base}/openai/deployments/{deployment_path}/images/generations"
        f"?api-version={resolved_api_version}"
    )


def default_edit_endpoint(
    resource_endpoint: str | None = None,
    deployment: str | None = None,
    api_version: str | None = None,
) -> str:
    resolved_resource = resource_endpoint or os.environ.get("AZURE_OPENAI_RESOURCE_ENDPOINT", "")
    resolved_deployment = deployment or os.environ.get("AZURE_OPENAI_IMAGE_DEPLOYMENT", "")
    resolved_api_version = api_version or os.environ.get(
        "AZURE_OPENAI_IMAGE_EDIT_API_VERSION",
        DEFAULT_EDIT_API_VERSION,
    )
    if not resolved_resource or not resolved_deployment:
        raise AzureImageGenerationError(
            "Set AZURE_OPENAI_IMAGE_EDIT_ENDPOINT, or configure both "
            "AZURE_OPENAI_RESOURCE_ENDPOINT and AZURE_OPENAI_IMAGE_DEPLOYMENT."
        )
    base = image_resource_endpoint(resolved_resource)
    deployment_path = urllib.parse.quote(resolved_deployment, safe="")
    return (
        f"{base}/openai/deployments/{deployment_path}/images/edits"
        f"?api-version={resolved_api_version}"
    )


def image_resource_endpoint(resource_endpoint: str) -> str:
    """Resolve a Foundry project URL to its account-level data-plane resource."""
    parsed = urllib.parse.urlsplit(resource_endpoint.strip())
    host = parsed.hostname or ""
    if host.casefold().endswith(".services.ai.azure.com"):
        image_host = host
        if parsed.port:
            image_host = f"{image_host}:{parsed.port}"
        return urllib.parse.urlunsplit((parsed.scheme or "https", image_host, "", "", "")).rstrip("/")
    return resource_endpoint.rstrip("/")


def normalize_image_endpoint(endpoint: str) -> str:
    """Remove API-version only from project-scoped OpenAI-compatible URLs."""
    parsed = urllib.parse.urlsplit(endpoint)
    if "/openai/v1/" not in parsed.path or "/api/projects/" not in parsed.path:
        return endpoint
    query = urllib.parse.urlencode(
        [
            (name, value)
            for name, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            if name.lower() != "api-version"
        ],
        doseq=True,
    )
    return urllib.parse.urlunsplit(parsed._replace(query=query))


def to_edit_endpoint(endpoint: str) -> str:
    if "/images/edits" in endpoint:
        return endpoint
    if "/images/generations" in endpoint:
        return endpoint.replace("/images/generations", "/images/edits", 1)
    raise AzureImageGenerationError("Azure image edit endpoint must contain /images/generations or /images/edits.")


def generate_image(
    *,
    prompt: str,
    output_dir: Path,
    bearer_token: str | None = None,
    api_key: str | None = None,
    token_provider: TokenProvider | None = None,
    endpoint: str | None = None,
    size: str = "2048x2048",
    quality: str = "high",
    output_format: str = "png",
    background: str | None = None,
    timeout: int = DEFAULT_IMAGE_TIMEOUT_SECONDS,
) -> GeneratedImage:
    resolved_token, resolved_key = _resolve_credentials(bearer_token, api_key, token_provider)
    stream_response = _environment_flag("PCP_IMAGE_STREAMING", default=False)
    request_payload = {
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": 1,
        "output_format": output_format,
    }
    if background:
        request_payload["background"] = background
    if stream_response:
        request_payload["stream"] = True
        request_payload["partial_images"] = _partial_image_count()
    url = normalize_image_endpoint(
        endpoint or os.environ.get("AZURE_OPENAI_IMAGE_ENDPOINT") or default_generation_endpoint()
    )
    if "/openai/v1/images/" in url:
        request_payload["model"] = _image_deployment()
    body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    started = time.perf_counter()
    response_payload = _post_generation_with_retry(
        url,
        body,
        resolved_token,
        resolved_key,
        token_provider,
        timeout,
        stream_response=stream_response,
    )

    elapsed_seconds = round(time.perf_counter() - started, 3)
    result = save_generated_image(response_payload, output_dir, f"generated_{time.strftime('%Y%m%d_%H%M%S')}")
    metadata_path = output_dir / f"{result.image_path.stem}.json"
    metadata_path.write_text(
        json.dumps(
            {
                "elapsed_seconds": elapsed_seconds,
                "endpoint": url,
                "request": request_payload,
                "image_path": str(result.image_path),
                "response": response_payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return GeneratedImage(
        image_path=result.image_path,
        metadata_path=metadata_path,
        elapsed_seconds=elapsed_seconds,
        usage=response_payload.get("usage", {}),
        response=response_payload,
        request=request_payload,
    )


def edit_image(
    *,
    prompt: str,
    reference_image_path: Path,
    additional_reference_paths: list[Path] | None = None,
    output_dir: Path,
    bearer_token: str | None = None,
    api_key: str | None = None,
    token_provider: TokenProvider | None = None,
    endpoint: str | None = None,
    size: str = "2048x2048",
    quality: str = "high",
    input_fidelity: str = "high",
    output_format: str = "png",
    timeout: int = DEFAULT_IMAGE_TIMEOUT_SECONDS,
) -> GeneratedImage:
    resolved_token, resolved_key = _resolve_credentials(bearer_token, api_key, token_provider)
    if not reference_image_path.exists():
        raise AzureImageGenerationError(f"Reference image does not exist: {reference_image_path}")
    reference_image_paths = [reference_image_path, *(additional_reference_paths or [])]
    for path in reference_image_paths:
        if not path.exists():
            raise AzureImageGenerationError(f"Reference image does not exist: {path}")
    request_payload: dict[str, Any] = {
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": 1,
        "output_format": output_format,
    }
    raw_url = (
        endpoint
        or os.environ.get("AZURE_OPENAI_IMAGE_EDIT_ENDPOINT")
        or os.environ.get("AZURE_OPENAI_IMAGE_ENDPOINT")
        or default_edit_endpoint()
    )
    url = normalize_image_endpoint(to_edit_endpoint(raw_url))
    deployment = os.environ.get("AZURE_OPENAI_IMAGE_DEPLOYMENT", "").strip()
    fidelity_target = f"{url}|{deployment}".casefold()
    if (
        input_fidelity
        and _deployment_supports_input_fidelity(deployment)
        and fidelity_target not in _INPUT_FIDELITY_UNSUPPORTED_TARGETS
    ):
        request_payload["input_fidelity"] = input_fidelity
    if "/openai/v1/images/" in url:
        request_payload["model"] = _image_deployment()
    content_type, body = build_multipart_body(request_payload, reference_image_paths)
    started = time.perf_counter()
    try:
        response_payload = _post_multipart_with_retry(
            url,
            body,
            content_type,
            resolved_token,
            resolved_key,
            token_provider,
            timeout,
        )
    except AzureImageGenerationError as exc:
        if "input_fidelity" not in request_payload or not _is_input_fidelity_unsupported_error(exc):
            raise
        _INPUT_FIDELITY_UNSUPPORTED_TARGETS.add(fidelity_target)
        request_payload.pop("input_fidelity", None)
        content_type, body = build_multipart_body(request_payload, reference_image_paths)
        response_payload = _post_multipart_with_retry(
            url,
            body,
            content_type,
            resolved_token,
            resolved_key,
            token_provider,
            timeout,
        )

    elapsed_seconds = round(time.perf_counter() - started, 3)
    result = save_generated_image(response_payload, output_dir, f"edited_{time.strftime('%Y%m%d_%H%M%S')}")
    metadata_path = output_dir / f"{result.image_path.stem}.json"
    metadata_path.write_text(
        json.dumps(
            {
                "mode": "edit",
                "elapsed_seconds": elapsed_seconds,
                "endpoint": url,
                "request": {
                    **request_payload,
                    "reference_images": [str(path) for path in reference_image_paths],
                },
                "image_path": str(result.image_path),
                "response": response_payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return GeneratedImage(
        image_path=result.image_path,
        metadata_path=metadata_path,
        elapsed_seconds=elapsed_seconds,
        usage=response_payload.get("usage", {}),
        response=response_payload,
        request=request_payload,
    )


def _deployment_supports_input_fidelity(deployment: str) -> bool:
    """GPT-Image-2 rejects the edit-only input_fidelity form field."""
    normalized = deployment.strip().casefold().replace("_", "-")
    if not normalized:
        return True
    return "gpt-image-2" not in normalized and "gpt-image-1-mini" not in normalized


def _is_input_fidelity_unsupported_error(exc: Exception) -> bool:
    message = str(exc).casefold()
    return "input_fidelity" in message and (
        "invalid_input_fidelity_model" in message
        or "does not support" in message
        or "not supported" in message
    )


def _resolve_credentials(
    bearer_token: str | None,
    api_key: str | None,
    token_provider: TokenProvider | None,
) -> tuple[str, str]:
    resolved_token = bearer_token or os.environ.get("AZURE_OPENAI_BEARER_TOKEN", "")
    resolved_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY", "")
    if not token_provider and not resolved_token and not resolved_key:
        raise AzureImageGenerationError(
            "Missing Azure OpenAI credentials. Configure Managed Identity, "
            "AZURE_OPENAI_BEARER_TOKEN, or AZURE_OPENAI_API_KEY."
        )
    return resolved_token, resolved_key


def _image_deployment() -> str:
    deployment = os.environ.get("AZURE_OPENAI_IMAGE_DEPLOYMENT", "").strip()
    if not deployment:
        raise AzureImageGenerationError(
            "AZURE_OPENAI_IMAGE_DEPLOYMENT is required for the Azure OpenAI v1 image endpoint."
        )
    return deployment


def _auth_headers(
    bearer_token: str,
    api_key: str,
    token_provider: TokenProvider | None,
) -> dict[str, str]:
    if token_provider:
        try:
            bearer_token = token_provider()
        except Exception as exc:
            raise AzureImageGenerationError(f"Azure OpenAI authentication refresh failed: {exc}") from exc
        if not bearer_token:
            raise AzureImageGenerationError("Azure OpenAI token provider returned an empty token.")
    if bearer_token:
        return {"Authorization": f"Bearer {bearer_token}"}
    return {"api-key": api_key}


def _post_generation_with_retry(
    url: str,
    body: bytes,
    bearer_token: str,
    api_key: str,
    token_provider: TokenProvider | None,
    timeout: int,
    *,
    stream_response: bool = False,
) -> dict[str, Any]:
    def make_request() -> urllib.request.Request:
        return urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                **_auth_headers(bearer_token, api_key, token_provider),
            },
            method="POST",
        )

    with _IMAGE_REQUEST_LOCK:
        return _post_with_retry(
            "generation",
            make_request,
            timeout,
            stream_response=stream_response,
        )


def build_multipart_body(
    fields: dict[str, Any],
    image_paths: Path | list[Path],
    image_field_name: str | None = None,
) -> tuple[str, bytes]:
    resolved_paths = [image_paths] if isinstance(image_paths, Path) else list(image_paths)
    if not resolved_paths:
        raise AzureImageGenerationError("At least one reference image is required.")
    resolved_field_name = image_field_name or ("image[]" if len(resolved_paths) > 1 else "image")
    boundary = f"----image-qa-mvp-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        if value is None or value == "":
            continue
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")

    for image_path in resolved_paths:
        mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{resolved_field_name}"; '
                f'filename="{image_path.name}"\r\n'
            ).encode("utf-8")
        )
        chunks.append(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
        chunks.append(image_path.read_bytes())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


def _post_multipart_with_retry(
    url: str,
    body: bytes,
    content_type: str,
    bearer_token: str,
    api_key: str,
    token_provider: TokenProvider | None,
    timeout: int,
) -> dict[str, Any]:
    def make_request() -> urllib.request.Request:
        return urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": content_type,
                **_auth_headers(bearer_token, api_key, token_provider),
            },
            method="POST",
        )

    with _IMAGE_REQUEST_LOCK:
        return _post_with_retry("edit", make_request, timeout)


def _post_with_retry(
    operation: str,
    make_request: Callable[[], urllib.request.Request],
    timeout: int,
    *,
    max_attempts: int = IMAGE_REQUEST_MAX_ATTEMPTS,
    stream_response: bool = False,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(make_request(), timeout=timeout) as response:
                if stream_response:
                    return _read_streaming_image_response(response)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            last_error = AzureImageGenerationError(
                f"Azure image {operation} failed: HTTP {exc.code}\n{error_body}"
            )
            if exc.code not in RETRYABLE_IMAGE_HTTP_STATUS:
                raise last_error from exc
            if attempt < max_attempts - 1:
                retry_after = _retry_after_seconds(exc, error_body)
                time.sleep(_retry_delay_seconds(attempt, retry_after=retry_after))
        except TRANSIENT_IMAGE_ERRORS as exc:
            detail = str(exc).strip() or type(exc).__name__
            last_error = exc
            if attempt < max_attempts - 1:
                time.sleep(_retry_delay_seconds(attempt))
                continue
            raise AzureImageGenerationError(
                f"Azure image {operation} connection failed after {max_attempts} attempts: {detail}"
            ) from exc
    raise AzureImageGenerationError(
        f"Azure image {operation} failed after {max_attempts} attempts: {last_error}"
    ) from last_error


def _read_streaming_image_response(response: Any) -> dict[str, Any]:
    """Convert image-generation SSE events to the existing JSON response shape."""

    latest_image_event: dict[str, Any] | None = None
    completed_event: dict[str, Any] | None = None
    data_lines: list[str] = []

    def consume_event() -> None:
        nonlocal latest_image_event, completed_event
        if not data_lines:
            return
        raw_data = "\n".join(data_lines)
        data_lines.clear()
        if raw_data == "[DONE]":
            return
        try:
            event = json.loads(raw_data)
        except json.JSONDecodeError as exc:
            raise AzureImageGenerationError(
                f"Azure image streaming returned invalid JSON: {raw_data[:240]}"
            ) from exc
        if event.get("b64_json") or event.get("url"):
            latest_image_event = event
        if event.get("type") in {"image_generation.completed", "image_edit.completed"}:
            completed_event = event

    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            consume_event()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    consume_event()

    final_event = completed_event or latest_image_event
    if not final_event:
        raise AzureImageGenerationError(
            "Azure image streaming response completed without an image event."
        )
    image_data = {
        key: final_event[key]
        for key in ("b64_json", "url", "revised_prompt")
        if final_event.get(key)
    }
    return {
        "created": final_event.get("created_at", int(time.time())),
        "data": [image_data],
        "usage": final_event.get("usage", {}),
        "stream_event_type": final_event.get("type", ""),
    }


def _environment_flag(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _partial_image_count() -> int:
    raw_value = os.environ.get("PCP_IMAGE_PARTIAL_IMAGES", "3")
    try:
        value = int(raw_value)
    except ValueError:
        value = 3
    return max(1, min(value, 3))


def _retry_after_seconds(exc: urllib.error.HTTPError, error_body: str) -> float | None:
    headers = exc.headers
    for name in ("retry-after-ms", "x-ms-retry-after-ms"):
        value = headers.get(name) if headers else None
        parsed = _positive_float(value)
        if parsed is not None:
            return min(parsed / 1000.0, IMAGE_REQUEST_MAX_RETRY_AFTER_SECONDS)

    for name in ("Retry-After", "x-ratelimit-reset-requests"):
        value = headers.get(name) if headers else None
        parsed = _positive_float(value)
        if parsed is not None:
            return min(parsed, IMAGE_REQUEST_MAX_RETRY_AFTER_SECONDS)

    body_match = re.search(
        r"(?:retry\s+after|try\s+again\s+in)\s+(\d+(?:\.\d+)?)\s*seconds?",
        error_body,
        flags=re.IGNORECASE,
    )
    if body_match:
        return min(float(body_match.group(1)), IMAGE_REQUEST_MAX_RETRY_AFTER_SECONDS)
    return None


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _retry_delay_seconds(attempt: int, *, retry_after: float | None = None) -> float:
    if attempt < len(IMAGE_REQUEST_RETRY_DELAYS):
        backoff = IMAGE_REQUEST_RETRY_DELAYS[attempt]
    else:
        backoff = IMAGE_REQUEST_RETRY_DELAYS[-1]
    delay = max(backoff, retry_after or 0.0)
    return delay + random.uniform(0.1, 0.9)


def save_generated_image(response: dict[str, Any], output_dir: Path, stem: str) -> GeneratedImage:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = response.get("data") or []
    if not data:
        raise AzureImageGenerationError("Azure image generation response did not contain data.")
    first = data[0]
    image_path = output_dir / f"{stem}.png"
    if "b64_json" in first:
        image_path.write_bytes(base64.b64decode(first["b64_json"]))
    elif "url" in first:
        with urllib.request.urlopen(first["url"], timeout=120) as response_obj:
            image_path.write_bytes(response_obj.read())
    else:
        raise AzureImageGenerationError("Azure image generation response did not contain b64_json or url.")
    return GeneratedImage(
        image_path=image_path,
        metadata_path=None,
        elapsed_seconds=0,
        usage=response.get("usage", {}),
        response=response,
    )
