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
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_RESOURCE_ENDPOINT = "https://ai-chengbian2072ai349864755390.cognitiveservices.azure.com"
DEFAULT_DEPLOYMENT = "gpt-image-2"
DEFAULT_API_VERSION = "2024-02-01"
DEFAULT_EDIT_API_VERSION = "2025-04-01-preview"
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


class AzureImageGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedImage:
    image_path: Path
    metadata_path: Path | None
    elapsed_seconds: float
    usage: dict[str, Any]
    response: dict[str, Any]


def default_generation_endpoint(
    resource_endpoint: str = DEFAULT_RESOURCE_ENDPOINT,
    deployment: str = DEFAULT_DEPLOYMENT,
    api_version: str = DEFAULT_API_VERSION,
) -> str:
    base = resource_endpoint.rstrip("/")
    return f"{base}/openai/deployments/{deployment}/images/generations?api-version={api_version}"


def default_edit_endpoint(
    resource_endpoint: str = DEFAULT_RESOURCE_ENDPOINT,
    deployment: str = DEFAULT_DEPLOYMENT,
    api_version: str = DEFAULT_EDIT_API_VERSION,
) -> str:
    base = resource_endpoint.rstrip("/")
    return f"{base}/openai/deployments/{deployment}/images/edits?api-version={api_version}"


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
    bearer_token: str,
    endpoint: str | None = None,
    size: str = "1024x1024",
    quality: str = "low",
    output_format: str = "png",
    timeout: int = 600,
) -> GeneratedImage:
    if not bearer_token:
        raise AzureImageGenerationError("Missing Azure OpenAI bearer token.")
    request_payload = {
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": 1,
        "output_format": output_format,
    }
    url = endpoint or os.environ.get("AZURE_OPENAI_IMAGE_ENDPOINT") or default_generation_endpoint()
    body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    started = time.perf_counter()
    response_payload = _post_generation_with_retry(url, body, bearer_token, timeout)

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
    )


def edit_image(
    *,
    prompt: str,
    reference_image_path: Path,
    additional_reference_paths: list[Path] | None = None,
    output_dir: Path,
    bearer_token: str,
    endpoint: str | None = None,
    size: str = "1024x1024",
    quality: str = "low",
    input_fidelity: str = "high",
    output_format: str = "png",
    timeout: int = 600,
) -> GeneratedImage:
    if not bearer_token:
        raise AzureImageGenerationError("Missing Azure OpenAI bearer token.")
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
    if input_fidelity:
        request_payload["input_fidelity"] = input_fidelity

    raw_url = (
        endpoint
        or os.environ.get("AZURE_OPENAI_IMAGE_EDIT_ENDPOINT")
        or os.environ.get("AZURE_OPENAI_IMAGE_ENDPOINT")
        or default_edit_endpoint()
    )
    url = to_edit_endpoint(raw_url)
    content_type, body = build_multipart_body(request_payload, reference_image_paths)
    started = time.perf_counter()
    response_payload = _post_multipart_with_retry(url, body, content_type, bearer_token, timeout)

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
    )


def _post_generation_with_retry(url: str, body: bytes, bearer_token: str, timeout: int) -> dict[str, Any]:
    def make_request() -> urllib.request.Request:
        return urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bearer_token}",
            },
            method="POST",
        )

    with _IMAGE_REQUEST_LOCK:
        return _post_with_retry("generation", make_request, timeout)


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
    timeout: int,
) -> dict[str, Any]:
    def make_request() -> urllib.request.Request:
        return urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": content_type,
                "Authorization": f"Bearer {bearer_token}",
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
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(make_request(), timeout=timeout) as response:
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
            last_error = exc
            if attempt < max_attempts - 1:
                time.sleep(_retry_delay_seconds(attempt))
    raise AzureImageGenerationError(
        f"Azure image {operation} failed after {max_attempts} attempts: {last_error}"
    ) from last_error


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
