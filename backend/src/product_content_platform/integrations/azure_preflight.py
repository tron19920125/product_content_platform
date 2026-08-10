from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from product_content_platform.integrations.azure_credentials import token_provider_from_env
from product_content_platform.integrations.azure_image_client import (
    default_edit_endpoint,
    default_generation_endpoint,
    normalize_image_endpoint,
)
from product_content_platform.quality.llm_reviewer import default_review_endpoint
from product_content_platform.settings import Settings


def run_preflight(settings: Settings) -> dict[str, Any]:
    """Validate runtime configuration and Azure authentication without invoking a model."""

    components = [
        _check_image_generation(settings),
        _check_vision_ocr(settings),
        _check_llm_review(settings),
    ]
    if any(item["status"] == "error" for item in components):
        overall = "error"
    elif all(item["status"] == "skipped" for item in components):
        overall = "local"
    else:
        overall = "ready"
    return {
        "status": overall,
        "generation_mode": settings.generation_mode,
        "qa_mode": settings.qa_mode,
        "auth_mode": os.environ.get("AZURE_AUTH_MODE", "static").strip().casefold(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "components": components,
    }


def _check_image_generation(settings: Settings) -> dict[str, Any]:
    if settings.generation_mode != "azure":
        return _component("image_generation", "skipped", "当前使用本地图片生成器。")
    try:
        generation_url = normalize_image_endpoint(
            os.environ.get("AZURE_OPENAI_IMAGE_ENDPOINT", "") or default_generation_endpoint()
        )
        edit_url = normalize_image_endpoint(
            os.environ.get("AZURE_OPENAI_IMAGE_EDIT_ENDPOINT", "") or default_edit_endpoint()
        )
        _require_https(generation_url)
        _require_https(edit_url)
        verification = _verify_auth(
            generation_url,
            key_names=("AZURE_OPENAI_BEARER_TOKEN", "AZURE_OPENAI_API_KEY"),
        )
        return _component(
            "image_generation",
            "ready",
            f"图片生成与参考图编辑路由有效；{verification}。",
            endpoint_host=_endpoint_host(generation_url),
        )
    except Exception as exc:  # preflight must report all components instead of aborting
        return _component("image_generation", "error", _concise_error(exc))


def _check_vision_ocr(settings: Settings) -> dict[str, Any]:
    if settings.qa_mode != "azure":
        return _component("vision_ocr", "skipped", "当前使用本地确定性质检。")
    try:
        endpoint = os.environ.get("AZURE_AI_VISION_ENDPOINT", "").strip()
        if not endpoint:
            raise ValueError("缺少 AZURE_AI_VISION_ENDPOINT。")
        _require_https(endpoint)
        verification = _verify_auth(
            endpoint,
            key_names=("AZURE_AI_VISION_BEARER_TOKEN", "AZURE_AI_VISION_KEY"),
        )
        return _component(
            "vision_ocr",
            "ready",
            f"OCR 端点配置有效；{verification}。",
            endpoint_host=_endpoint_host(endpoint),
        )
    except Exception as exc:
        return _component("vision_ocr", "error", _concise_error(exc))


def _check_llm_review(settings: Settings) -> dict[str, Any]:
    if settings.qa_mode != "azure":
        return _component("llm_review", "skipped", "当前不调用 Azure LLM 审查。")
    try:
        endpoint = os.environ.get("AZURE_OPENAI_REVIEW_ENDPOINT", "").strip() or default_review_endpoint(
            os.environ.get("AZURE_OPENAI_RESOURCE_ENDPOINT", ""),
            os.environ.get("AZURE_OPENAI_REVIEW_MODEL", "").strip()
            or os.environ.get("AZURE_OPENAI_REVIEW_DEPLOYMENT", "").strip()
            or "gpt-5-mini",
            os.environ.get("AZURE_OPENAI_REVIEW_API_VERSION", "preview"),
        )
        _require_https(endpoint)
        verification = _verify_auth(
            endpoint,
            key_names=("AZURE_OPENAI_BEARER_TOKEN", "AZURE_OPENAI_API_KEY"),
        )
        return _component(
            "llm_review",
            "ready",
            f"LLM 审查路由有效；{verification}。",
            endpoint_host=_endpoint_host(endpoint),
        )
    except Exception as exc:
        return _component("llm_review", "error", _concise_error(exc))


def _verify_auth(endpoint: str, *, key_names: tuple[str, ...]) -> str:
    mode = os.environ.get("AZURE_AUTH_MODE", "static").strip().casefold()
    if mode == "static":
        if not any(os.environ.get(name, "").strip() for name in key_names):
            raise ValueError(f"静态认证缺少凭据：请配置 {' 或 '.join(key_names)}。")
        return "静态凭据已配置（未调用模型）"

    provider: Callable[[], str] | None = token_provider_from_env(endpoint=endpoint)
    if provider is None:
        raise ValueError("Azure 身份令牌提供器未启用。")
    token = provider()
    if not token:
        raise ValueError("Azure 身份认证返回了空令牌。")
    return "Azure 身份令牌获取成功（未调用模型）"


def _require_https(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise ValueError("Azure 端点必须是包含有效主机名的 HTTPS 地址。")


def _endpoint_host(endpoint: str) -> str:
    return urlparse(endpoint).hostname or ""


def _component(
    name: str,
    status: str,
    message: str,
    *,
    endpoint_host: str = "",
) -> dict[str, str]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "endpoint_host": endpoint_host,
    }


def _concise_error(exc: Exception) -> str:
    first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    if len(first_line) > 320:
        first_line = f"{first_line[:317]}..."
    return first_line

