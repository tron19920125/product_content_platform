from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from product_content_platform.quality.text_review import OcrLine


DEFAULT_API_VERSION = "2023-10-01"
VISION_REQUEST_MAX_ATTEMPTS = 4
VISION_REQUEST_RETRY_DELAYS = (1.0, 2.0, 4.0)
RETRYABLE_VISION_HTTP_STATUS = {408, 429, 500, 502, 503, 504}
TRANSIENT_VISION_ERRORS = (
    http.client.IncompleteRead,
    http.client.RemoteDisconnected,
    socket.timeout,
    TimeoutError,
    ConnectionError,
    ssl.SSLError,
    urllib.error.URLError,
)
TokenProvider = Callable[[], str]
CURL_STATUS_MARKER = b"\n__IMAGE_QA_HTTP_STATUS__:"


class AzureVisionOcrError(RuntimeError):
    pass


def build_read_url(endpoint: str, api_version: str = DEFAULT_API_VERSION) -> str:
    base = endpoint.rstrip("/")
    return f"{base}/computervision/imageanalysis:analyze?api-version={api_version}&features=read"


def _response_dimensions(data: dict[str, Any]) -> tuple[float | None, float | None]:
    metadata = data.get("metadata", {})
    width = metadata.get("width") or metadata.get("widthInPixels")
    height = metadata.get("height") or metadata.get("heightInPixels")
    try:
        return float(width), float(height)
    except (TypeError, ValueError):
        return None, None


def _normalize_bbox(values: list[float], width: float | None, height: float | None) -> tuple[float, float, float, float] | None:
    if len(values) != 4:
        return None
    x1, y1, x2, y2 = min(values[0], values[2]), min(values[1], values[3]), max(values[0], values[2]), max(values[1], values[3])
    if max(x1, y1, x2, y2) <= 1.0:
        return (x1, y1, x2, y2)
    if not width or not height:
        return None
    return (
        max(0.0, min(1.0, x1 / width)),
        max(0.0, min(1.0, y1 / height)),
        max(0.0, min(1.0, x2 / width)),
        max(0.0, min(1.0, y2 / height)),
    )


def _parse_line_bbox(row: dict[str, Any], width: float | None, height: float | None) -> tuple[float, float, float, float] | None:
    polygon = row.get("boundingPolygon") or row.get("bounding_polygon")
    if isinstance(polygon, list) and polygon:
        points = []
        for point in polygon:
            if not isinstance(point, dict):
                continue
            try:
                points.append((float(point["x"]), float(point["y"])))
            except (KeyError, TypeError, ValueError):
                continue
        if points:
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            return _normalize_bbox([min(xs), min(ys), max(xs), max(ys)], width, height)

    bounding_box = row.get("boundingBox") or row.get("bbox")
    if isinstance(bounding_box, list):
        try:
            values = [float(item) for item in bounding_box]
        except (TypeError, ValueError):
            return None
        if len(values) == 8:
            xs = values[0::2]
            ys = values[1::2]
            return _normalize_bbox([min(xs), min(ys), max(xs), max(ys)], width, height)
        if len(values) == 4:
            x, y, w, h = values
            return _normalize_bbox([x, y, x + w, y + h], width, height)
    return None


def parse_vision_response(data: dict[str, Any]) -> list[OcrLine]:
    width, height = _response_dimensions(data)
    lines = []
    for block in data.get("readResult", {}).get("blocks", []):
        for row in block.get("lines", []):
            lines.append(
                OcrLine(
                    text=str(row.get("text", "")),
                    confidence=row.get("confidence"),
                    bbox=_parse_line_bbox(row, width, height),
                )
            )
    return lines


def _post_with_urllib(
    url: str,
    image_bytes: bytes,
    headers: dict[str, str],
    timeout: int,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=image_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None and hasattr(response, "getcode"):
                status = response.getcode()
            return int(status or 200), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def _curl_config(headers: dict[str, str]) -> bytes:
    lines = []
    for name, value in headers.items():
        escaped = f"{name}: {value}".replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'header = "{escaped}"')
    return ("\n".join(lines) + "\n").encode("utf-8")


def _post_with_curl(
    curl_path: str,
    url: str,
    image_path: Path,
    headers: dict[str, str],
    timeout: int,
) -> tuple[int, bytes]:
    result = subprocess.run(
        [
            curl_path,
            "--config",
            "-",
            "--silent",
            "--show-error",
            "--http1.1",
            "--max-time",
            str(timeout),
            "--request",
            "POST",
            "--data-binary",
            f"@{image_path}",
            "--write-out",
            CURL_STATUS_MARKER.decode("ascii") + "%{http_code}",
            url,
        ],
        input=_curl_config(headers),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise ConnectionError(f"curl exit {result.returncode}: {error}")
    body, marker, status = result.stdout.rpartition(CURL_STATUS_MARKER)
    if not marker:
        raise ConnectionError("curl response did not contain an HTTP status marker")
    try:
        return int(status.strip()), body
    except ValueError as exc:
        raise ConnectionError(f"curl returned an invalid HTTP status: {status!r}") from exc


def read_image_text(
    image_path: str | Path,
    *,
    endpoint: str | None = None,
    api_key: str | None = None,
    bearer_token: str | None = None,
    timeout: int = 120,
    max_attempts: int = VISION_REQUEST_MAX_ATTEMPTS,
    token_provider: TokenProvider | None = None,
    transport: str | None = None,
) -> list[OcrLine]:
    resolved_endpoint = endpoint or os.environ.get("AZURE_AI_VISION_ENDPOINT", "")
    resolved_key = api_key or os.environ.get("AZURE_AI_VISION_KEY", "")
    resolved_token = bearer_token or os.environ.get("AZURE_AI_VISION_BEARER_TOKEN", "")
    if not resolved_endpoint:
        raise AzureVisionOcrError("Missing Azure Vision endpoint. Set AZURE_AI_VISION_ENDPOINT.")
    if not resolved_key and not resolved_token:
        raise AzureVisionOcrError("Missing Azure Vision credentials. Set AZURE_AI_VISION_KEY or AZURE_AI_VISION_BEARER_TOKEN.")

    resolved_image_path = Path(image_path)
    image_bytes = resolved_image_path.read_bytes()
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    requested_transport = (transport or os.environ.get("AZURE_VISION_HTTP_TRANSPORT", "auto")).strip().casefold()
    if requested_transport not in {"auto", "curl", "urllib"}:
        raise ValueError("transport must be auto, curl, or urllib")
    curl_path = shutil.which("curl") if requested_transport != "urllib" else None
    if requested_transport == "curl" and not curl_path:
        raise AzureVisionOcrError("Azure Vision OCR 配置为 curl 传输，但系统未找到 curl。")

    last_error: Exception | None = None
    transient_attempt = 0
    refreshed_token = False
    using_bearer = bool(resolved_token)
    used_key_fallback = False
    while transient_attempt < max_attempts:
        headers = {"Content-Type": "application/octet-stream"}
        if using_bearer:
            headers["Authorization"] = f"Bearer {resolved_token}"
        else:
            headers["Ocp-Apim-Subscription-Key"] = resolved_key
        try:
            if curl_path:
                status, raw_body = _post_with_curl(
                    curl_path,
                    build_read_url(resolved_endpoint),
                    resolved_image_path,
                    headers,
                    timeout,
                )
            else:
                status, raw_body = _post_with_urllib(
                    build_read_url(resolved_endpoint),
                    image_bytes,
                    headers,
                    timeout,
                )
            body = raw_body.decode("utf-8", errors="replace")
            if 200 <= status < 300:
                return parse_vision_response(json.loads(body))
            if status == 401 and using_bearer:
                if token_provider and not refreshed_token:
                    refreshed_token = True
                    try:
                        fresh_token = token_provider()
                    except Exception as refresh_error:
                        raise AzureVisionOcrError(f"Azure Vision OCR 认证刷新失败：{refresh_error}") from refresh_error
                    if fresh_token:
                        resolved_token = fresh_token
                        continue
                if resolved_key and not used_key_fallback:
                    using_bearer = False
                    used_key_fallback = True
                    continue
            if status not in RETRYABLE_VISION_HTTP_STATUS:
                raise AzureVisionOcrError(f"Azure Vision OCR 调用失败：HTTP {status}\n{body}")
            last_error = AzureVisionOcrError(f"HTTP {status}: {body}")
        except TRANSIENT_VISION_ERRORS as exc:
            last_error = exc

        transient_attempt += 1
        if transient_attempt < max_attempts:
            time.sleep(_vision_retry_delay_seconds(transient_attempt - 1))

    raise AzureVisionOcrError(
        f"Azure Vision OCR 调用失败，已自动重试 {max_attempts} 次：{last_error}"
    ) from last_error


def _vision_retry_delay_seconds(attempt: int) -> float:
    if attempt < len(VISION_REQUEST_RETRY_DELAYS):
        return VISION_REQUEST_RETRY_DELAYS[attempt]
    return VISION_REQUEST_RETRY_DELAYS[-1]
