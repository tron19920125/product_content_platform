from __future__ import annotations

import base64
import http.client
import json
import mimetypes
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from product_content_platform.quality.review_requirements import requirements_with_fallback
from product_content_platform.quality.text_review import bbox_center_inside_region, parse_bbox


DEFAULT_RESOURCE_ENDPOINT = ""
DEFAULT_REVIEW_MODEL = "gpt-5.6-sol"
DEFAULT_REVIEW_DEPLOYMENT = DEFAULT_REVIEW_MODEL
DEFAULT_REVIEW_API_VERSION = "2025-04-01-preview"
DEFAULT_REVIEW_MAX_OUTPUT_TOKENS = 6000
LLM_REQUEST_MAX_ATTEMPTS = 4
LLM_REQUEST_RETRY_DELAYS = (1.0, 2.0, 4.0)
RETRYABLE_LLM_HTTP_STATUS = {408, 429, 500, 502, 503, 504}
TRANSIENT_LLM_ERRORS = (
    http.client.IncompleteRead,
    http.client.RemoteDisconnected,
    socket.timeout,
    TimeoutError,
    ConnectionError,
    ssl.SSLError,
    urllib.error.URLError,
)

SEVERITY_RANK = {"P0": 4, "P1": 3, "P2": 2, "P3": 1}


class LlmReviewerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReviewEvidence:
    mode: str
    user_prompt: str
    generated_ocr_lines: list[dict[str, Any]] = field(default_factory=list)
    reference_ocr_lines: list[dict[str, Any]] = field(default_factory=list)
    visual_review: dict[str, Any] | None = None
    generated_image_path: str = ""
    reference_image_path: str = ""
    product_reference_image_path: str = ""
    generation: dict[str, Any] | None = None
    review_plan: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        visual_review = self.visual_review or {}
        target_region = _target_region_from_visual_review(visual_review)
        review_plan = dict(self.review_plan or {})
        review_plan["requirements"] = requirements_with_fallback(review_plan)
        return {
            "mode": self.mode,
            "user_prompt": self.user_prompt,
            "generated_image_path": self.generated_image_path,
            "reference_image_path": self.reference_image_path,
            "product_reference_image_path": self.product_reference_image_path,
            "generated_ocr_lines": self.generated_ocr_lines,
            "reference_ocr_lines": self.reference_ocr_lines,
            "target_region": target_region,
            "target_generated_ocr_lines": _lines_inside_region(self.generated_ocr_lines, target_region),
            "target_reference_ocr_lines": _lines_inside_region(self.reference_ocr_lines, target_region),
            "outside_target_generated_ocr_lines": _lines_outside_region(self.generated_ocr_lines, target_region),
            "outside_target_reference_ocr_lines": _lines_outside_region(self.reference_ocr_lines, target_region),
            "review_policy": {
                "language": "中文",
                "verdict": {
                    "pass": "所有审查计划中的要求均有证据支持，且每个审查项都是 pass。",
                    "review": "没有明确失败项，但至少一项因图片、OCR 或参考证据不足而无法确认。",
                    "fail": "任一必须出现、必须移除、必须保留或其他关键要求明确不满足。",
                },
                "edit_text_scope": (
                    "For edit tasks, first compare target_reference_ocr_lines with target_generated_ocr_lines. "
                    "Only judge old-copy removal inside the target edit region when target_region is present."
                ),
                "non_target_scope": (
                    "OCR text outside the target edit region is reference-consistency evidence. Do not fail solely "
                    "because product logo, brand mark, model mark, or appliance body labels remain outside that region "
                    "unless the user explicitly requested removing them."
                ),
                "layout_stability": (
                    "For edit tasks, judge whether composition, product placement, text placement, margins, and "
                    "non-target regions remain stable using both images and visual-difference evidence."
                ),
                "brand_consistency": (
                    "Judge only evidence available in the prompt and reference image: preserve existing logo, model "
                    "marks, product identity, and visual style; reject invented or visibly damaged brand marks. "
                    "Do not claim formal brand-guideline compliance without an explicit brand specification."
                ),
                "product_replacement_scope": (
                    "For replace_product tasks, the source slice is the authority for product geometry, placement, "
                    "angle, perspective, occlusion, layout, text, background, and non-product content. The target "
                    "product reference is the authority for product identity, color, material, door/drum, control "
                    "panel, logo placement, and visible structural details."
                ),
            },
            "visual_review": visual_review,
            "generation": self.generation or {},
            "review_plan": review_plan,
        }


@dataclass(frozen=True)
class LlmReviewResult:
    status: str
    severity: str
    confidence: float
    summary: str
    review_items: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    suggested_fix_prompt: str
    raw_response: dict[str, Any]
    score_breakdown: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "severity": self.severity,
            "confidence": self.confidence,
            "summary": self.summary,
            "review_items": self.review_items,
            "issues": self.issues,
            "suggested_fix_prompt": self.suggested_fix_prompt,
            "score_breakdown": self.score_breakdown,
            "raw_response": self.raw_response,
        }


ReviewClient = Callable[[list[dict[str, Any]]], dict[str, Any] | str]
TokenProvider = Callable[[], str]


def default_review_endpoint(
    resource_endpoint: str = DEFAULT_RESOURCE_ENDPOINT,
    deployment: str = DEFAULT_REVIEW_DEPLOYMENT,
    api_version: str = DEFAULT_REVIEW_API_VERSION,
) -> str:
    if not resource_endpoint:
        raise LlmReviewerError(
            "Set AZURE_OPENAI_REVIEW_ENDPOINT or AZURE_OPENAI_RESOURCE_ENDPOINT."
        )
    base = resource_endpoint.rstrip("/")
    # Keep the deployment argument for callers that used the previous helper signature.
    _ = deployment
    return f"{base}/openai/responses?api-version={api_version}"


def build_review_messages(evidence: ReviewEvidence) -> list[dict[str, Any]]:
    evidence_json = json.dumps(evidence.to_dict(), ensure_ascii=False, indent=2)
    output_schema = {
        "status": "pass | review | fail",
        "confidence": "0.0-1.0",
        "summary": "中文短结论",
        "review_items": [
            {
                "category": "text_accuracy | prompt_following | layout_position | reference_consistency | visual_quality | other",
                "requirement_id": "必须对应 review_plan.requirements 中的一个 id",
                "severity": "P1 | P2 | P3",
                "expected": "用中文说明提示词要求什么",
                "observed": "用中文说明证据显示什么",
                "evidence": "generated_ocr | reference_ocr | visual_review | prompt | inferred",
                "result": "pass | review | fail",
                "message": "用中文给出审查说明",
            }
        ],
        "score_breakdown": {
            "text_accuracy": "0-100",
            "product_consistency": "0-100",
            "layout_stability": "0-100",
            "brand_compliance": "0-100",
        },
        "suggested_fix_prompt": "不需要修复时返回空字符串；需要修复时用中文描述修复提示词",
    }
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Review the generated image using this evidence JSON. The evidence may contain Chinese text. "
                "If target_region exists, use target_*_ocr_lines for edit-text replacement/removal checks, and "
                "use outside_target_*_ocr_lines only for non-target consistency unless the prompt says otherwise.\n\n"
                f"EVIDENCE JSON:\n{evidence_json}\n\n"
                "Return JSON with exactly this shape:\n"
                f"{json.dumps(output_schema, ensure_ascii=False, indent=2)}"
            ),
        }
    ]
    generated_image = _image_content_part(evidence.generated_image_path)
    if generated_image:
        user_content.extend([{"type": "text", "text": "生成或编辑后的候选图："}, generated_image])
    reference_image = _image_content_part(evidence.reference_image_path)
    if reference_image:
        user_content.extend([{"type": "text", "text": "原始参考图或原切片："}, reference_image])
    product_reference_image = _image_content_part(evidence.product_reference_image_path)
    if product_reference_image:
        user_content.extend([{"type": "text", "text": "目标产品参考图："}, product_reference_image])

    return [
        {
            "role": "system",
            "content": (
                "You are an image-generation QA reviewer. You are the primary reviewer, not a rule matcher. "
                "Infer what must be checked from the user's prompt, then judge the generated image using OCR "
                "evidence, target-region evidence, visual-difference evidence, and the structured review_plan. "
                "Return exactly one review_item for every entry in review_plan.requirements and copy its id into "
                "review_item.requirement_id. Do not omit a requirement; use result=review when evidence is insufficient. "
                "For edit tasks, first locate the requested text edit by comparing target_reference_ocr_lines "
                "and target_generated_ocr_lines when target_region is present. Only judge old-copy removal "
                "inside the target edit region. OCR text outside the target edit region is mainly for "
                "reference consistency and product preservation checks; do not fail solely because a product logo, "
                "brand mark, model mark, or appliance body label remains outside that region unless the user "
                "explicitly asked to remove it. Whole-image review should focus on product/reference consistency, "
                "layout stability, visual quality, and whether the generated image satisfies the prompt. "
                "For replace_product tasks, compare three roles separately: the source slice defines the product's "
                "geometry, placement, angle, perspective, occlusion, layout, text, background, and all non-product "
                "content; the target product reference defines product identity and visible appearance; the generated "
                "candidate must combine both. Fail clear wrong-product, wrong product count, major structural mismatch, "
                "product relocation, broken occlusion, or material non-product drift. Use review rather than inventing "
                "a detail that is not visible in the target product reference. "
                "Apply this verdict policy strictly: FAIL if any review_item result is fail or any explicit "
                "must_appear, must_not_appear, or must_preserve requirement is violated; REVIEW if there is no "
                "failure but any required check lacks enough evidence or any review_item result is review; PASS "
                "only when every planned requirement is covered and every review_item result is pass. Scores do "
                "not determine the verdict. For layout_stability, compare composition, product placement, text "
                "placement, margins, and non-target changes. For brand_compliance, judge reference-based brand "
                "consistency only; never imply a formal brand-guideline audit unless brand rules were provided. "
                "All natural-language fields in the JSON response must be written in 中文, including summary, "
                "review_items.expected, review_items.observed, review_items.message, and suggested_fix_prompt. "
                "Return only valid JSON."
            ),
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]


def review_image_with_llm(
    evidence: ReviewEvidence,
    *,
    client: ReviewClient | None = None,
    bearer_token: str | None = None,
    api_key: str | None = None,
    endpoint: str | None = None,
    timeout: int = 120,
    token_provider: TokenProvider | None = None,
) -> LlmReviewResult:
    messages = build_review_messages(evidence)
    response = client(messages) if client else call_azure_chat_review(
        messages,
        bearer_token=bearer_token,
        api_key=api_key,
        endpoint=endpoint,
        timeout=timeout,
        token_provider=token_provider,
    )
    requirements = requirements_with_fallback(evidence.review_plan or {})
    return parse_llm_review_response(response, requirements=requirements)


def call_azure_chat_review(
    messages: list[dict[str, Any]],
    *,
    bearer_token: str | None = None,
    api_key: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    timeout: int = 120,
    max_attempts: int = LLM_REQUEST_MAX_ATTEMPTS,
    token_provider: TokenProvider | None = None,
) -> str:
    url = endpoint or os.environ.get("AZURE_OPENAI_REVIEW_ENDPOINT") or default_review_endpoint(
        os.environ.get("AZURE_OPENAI_RESOURCE_ENDPOINT", DEFAULT_RESOURCE_ENDPOINT),
        os.environ.get(
            "AZURE_OPENAI_REVIEW_MODEL",
            os.environ.get("AZURE_OPENAI_REVIEW_DEPLOYMENT", DEFAULT_REVIEW_MODEL),
        ),
        os.environ.get("AZURE_OPENAI_REVIEW_API_VERSION", DEFAULT_REVIEW_API_VERSION),
    )
    resolved_model = (
        model
        or os.environ.get("AZURE_OPENAI_REVIEW_MODEL")
        or os.environ.get("AZURE_OPENAI_REVIEW_DEPLOYMENT")
        or DEFAULT_REVIEW_MODEL
    )
    resolved_token = bearer_token or os.environ.get("AZURE_OPENAI_BEARER_TOKEN", "")
    resolved_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY", "")
    if token_provider:
        try:
            resolved_token = token_provider()
        except Exception as exc:
            raise LlmReviewerError(f"LLM 审查认证失败：{exc}") from exc
    if not resolved_token and not resolved_key:
        raise LlmReviewerError(
            "Missing LLM review credentials. Configure Managed Identity, "
            "AZURE_OPENAI_BEARER_TOKEN, or AZURE_OPENAI_API_KEY."
        )

    uses_responses_api = _is_responses_endpoint(url)
    request_payload = (
        _build_responses_request(messages, model=resolved_model)
        if uses_responses_api
        else {
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
    )
    body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    payload: dict[str, Any] | None = None
    last_error: Exception | None = None
    transient_attempt = 0
    refreshed_token = False
    using_bearer = bool(resolved_token)
    used_key_fallback = False
    while transient_attempt < max_attempts:
        headers = {"Content-Type": "application/json"}
        if using_bearer:
            headers["Authorization"] = f"Bearer {resolved_token}"
        else:
            headers["api-key"] = resolved_key
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 401 and using_bearer:
                if token_provider and not refreshed_token:
                    refreshed_token = True
                    try:
                        fresh_token = token_provider()
                    except Exception as refresh_error:
                        raise LlmReviewerError(f"LLM 审查认证刷新失败：{refresh_error}") from refresh_error
                    if fresh_token:
                        resolved_token = fresh_token
                        continue
                if resolved_key and not used_key_fallback:
                    using_bearer = False
                    used_key_fallback = True
                    continue
            if exc.code not in RETRYABLE_LLM_HTTP_STATUS:
                raise LlmReviewerError(f"LLM 审查调用失败：HTTP {exc.code}\n{error_body}") from exc
            last_error = LlmReviewerError(f"HTTP {exc.code}: {error_body}")
        except TRANSIENT_LLM_ERRORS as exc:
            last_error = exc

        transient_attempt += 1
        if transient_attempt < max_attempts:
            time.sleep(_llm_retry_delay_seconds(transient_attempt - 1))

    if payload is None:
        raise LlmReviewerError(
            f"LLM 审查调用失败，已自动重试 {max_attempts} 次：{last_error}"
        ) from last_error
    if uses_responses_api:
        return _extract_responses_output_text(payload)
    choices = payload.get("choices") or []
    if not choices:
        raise LlmReviewerError("LLM review response did not contain choices.")
    content = choices[0].get("message", {}).get("content", "")
    if not content:
        raise LlmReviewerError("LLM review response did not contain message content.")
    return content


def _is_responses_endpoint(url: str) -> bool:
    return "/openai/responses" in url.split("?", 1)[0].rstrip("/")


def _build_responses_request(messages: list[dict[str, Any]], *, model: str) -> dict[str, Any]:
    instructions: list[str] = []
    response_input: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content", "")
        if role in {"system", "developer"}:
            instructions.extend(_text_parts(content))
            continue
        response_input.append(
            {
                "role": role if role in {"user", "assistant"} else "user",
                "content": _responses_content_parts(content),
            }
        )
    _ensure_json_request_in_input(response_input)

    try:
        max_output_tokens = int(
            os.environ.get("AZURE_OPENAI_REVIEW_MAX_OUTPUT_TOKENS", DEFAULT_REVIEW_MAX_OUTPUT_TOKENS)
        )
    except (TypeError, ValueError):
        max_output_tokens = DEFAULT_REVIEW_MAX_OUTPUT_TOKENS
    payload: dict[str, Any] = {
        "model": model,
        "input": response_input,
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": max(1, max_output_tokens),
    }
    if instructions:
        payload["instructions"] = "\n\n".join(instructions)
    return payload


def _ensure_json_request_in_input(response_input: list[dict[str, Any]]) -> None:
    input_text = json.dumps(response_input, ensure_ascii=False).casefold()
    if "json" in input_text:
        return
    json_instruction = {"type": "input_text", "text": "Return only valid JSON."}
    for message in response_input:
        if message.get("role") == "user" and isinstance(message.get("content"), list):
            message["content"].insert(0, json_instruction)
            return
    response_input.insert(0, {"role": "user", "content": [json_instruction]})


def _text_parts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content] if content else []
    if not isinstance(content, list):
        return [str(content)] if content is not None else []
    texts = []
    for part in content:
        if isinstance(part, str):
            texts.append(part)
        elif isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
            text = str(part.get("text") or "")
            if text:
                texts.append(text)
    return texts


def _responses_content_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "input_text", "text": content}]
    if not isinstance(content, list):
        return [{"type": "input_text", "text": str(content)}]

    converted: list[dict[str, Any]] = []
    for part in content:
        if isinstance(part, str):
            converted.append({"type": "input_text", "text": part})
            continue
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type in {"text", "input_text"}:
            converted.append({"type": "input_text", "text": str(part.get("text") or "")})
        elif part_type in {"image_url", "input_image"}:
            image_value = part.get("image_url")
            detail = part.get("detail")
            if isinstance(image_value, dict):
                detail = detail or image_value.get("detail")
                image_value = image_value.get("url")
            if image_value:
                image_part = {"type": "input_image", "image_url": str(image_value)}
                if detail:
                    image_part["detail"] = str(detail)
                converted.append(image_part)
    return converted


def _extract_responses_output_text(payload: dict[str, Any]) -> str:
    direct_text = payload.get("output_text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text

    texts: list[str] = []
    for output_item in payload.get("output") or []:
        if not isinstance(output_item, dict):
            continue
        for content_part in output_item.get("content") or []:
            if not isinstance(content_part, dict) or content_part.get("type") != "output_text":
                continue
            text = content_part.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
    if texts:
        return "".join(texts)

    error = payload.get("error")
    if error:
        raise LlmReviewerError(f"LLM Responses API 返回错误：{error}")
    status = str(payload.get("status") or "unknown")
    incomplete_details = payload.get("incomplete_details")
    details = f"，详情：{incomplete_details}" if incomplete_details else ""
    raise LlmReviewerError(f"LLM Responses API 未返回文本，状态：{status}{details}")


def _llm_retry_delay_seconds(attempt: int) -> float:
    if attempt < len(LLM_REQUEST_RETRY_DELAYS):
        return LLM_REQUEST_RETRY_DELAYS[attempt]
    return LLM_REQUEST_RETRY_DELAYS[-1]


def parse_llm_review_response(
    response: dict[str, Any] | str,
    *,
    requirements: list[dict[str, str]] | None = None,
) -> LlmReviewResult:
    payload = response if isinstance(response, dict) else json.loads(_extract_json_object(response))
    status = _normalize_status(payload.get("status"))
    review_items = _normalize_review_items(payload.get("review_items"))
    review_items = _ensure_requirement_coverage(review_items, requirements or [])
    item_status = _worst_status([item.get("result") for item in review_items]) if review_items else "pass"
    status = _worst_status([status, item_status])
    issues = [_issue_from_review_item(item, index) for index, item in enumerate(review_items) if item.get("result") != "pass"]
    severity = _max_severity([issue["severity"] for issue in issues])
    if status == "fail" and severity == "P3":
        severity = "P1"
    confidence = _clamp_float(payload.get("confidence"), 0.0, 1.0, default=0.0)
    score_breakdown = _normalize_score_breakdown(payload.get("score_breakdown"), review_items)
    return LlmReviewResult(
        status=status,
        severity=severity,
        confidence=confidence,
        summary=str(payload.get("summary", "")).strip(),
        review_items=review_items,
        issues=issues,
        suggested_fix_prompt=str(payload.get("suggested_fix_prompt", "")).strip(),
        raw_response=payload,
        score_breakdown=score_breakdown,
    )


def render_llm_markdown_report(result: LlmReviewResult, evidence: ReviewEvidence) -> str:
    lines = [
        "# LLM Image Review",
        "",
        f"- Status: `{result.status}`",
        f"- Severity: `{result.severity}`",
        f"- Confidence: `{result.confidence}`",
        f"- Mode: `{evidence.mode}`",
        "",
        "## Summary",
        "",
        result.summary or "No summary returned.",
        "",
        "## Review Items",
        "",
    ]
    if result.review_items:
        for item in result.review_items:
            lines.append(
                "- "
                f"`{item.get('severity', 'P3')}` "
                f"`{item.get('category', 'other')}` "
                f"`{item.get('result', 'review')}`: "
                f"{item.get('message') or item.get('observed') or 'No message.'}"
            )
    else:
        lines.append("- No issues detected by the LLM reviewer.")
    lines.extend(
        [
            "",
            "## Suggested Fix Prompt",
            "",
            result.suggested_fix_prompt or "No fix prompt needed.",
            "",
            "## Evidence",
            "",
            "```json",
            json.dumps(evidence.to_dict(), ensure_ascii=False, indent=2),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    raise LlmReviewerError("LLM review response did not contain a JSON object.")


def _image_content_part(image_path: str) -> dict[str, Any] | None:
    if not image_path:
        return None
    path = Path(image_path)
    if not path.exists() or not path.is_file():
        return None
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{encoded}", "detail": "high"},
    }


def image_content_part(image_path: str) -> dict[str, Any] | None:
    return _image_content_part(image_path)


def _normalize_review_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        normalized["category"] = str(normalized.get("category") or "other")
        normalized["requirement_id"] = str(normalized.get("requirement_id") or "").strip()
        normalized["severity"] = _normalize_severity(normalized.get("severity"))
        normalized["result"] = _normalize_status(normalized.get("result"))
        normalized["message"] = str(normalized.get("message") or normalized.get("observed") or "").strip()
        items.append(normalized)
    return items


def _ensure_requirement_coverage(
    review_items: list[dict[str, Any]],
    requirements: list[dict[str, str]],
) -> list[dict[str, Any]]:
    covered = {str(item.get("requirement_id") or "").strip() for item in review_items}
    completed = list(review_items)
    for requirement in requirements:
        requirement_id = str(requirement.get("id") or "").strip()
        if not requirement_id or requirement_id in covered:
            continue
        text = str(requirement.get("text") or "").strip()
        completed.append(
            {
                "category": _category_for_requirement(requirement.get("type")),
                "requirement_id": requirement_id,
                "severity": "P2",
                "expected": text,
                "observed": "Agent 审查结果未覆盖此项要求。",
                "evidence": "review_plan",
                "result": "review",
                "message": f"缺少审查项 {requirement_id} 的独立结论，需重新审查。",
            }
        )
    return completed


def _category_for_requirement(value: Any) -> str:
    return {
        "must_appear": "text_accuracy",
        "must_not_appear": "text_accuracy",
        "must_preserve": "reference_consistency",
        "review_checks": "other",
    }.get(str(value or ""), "other")


def _issue_from_review_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    category = str(item.get("category") or "other")
    return {
        "code": category,
        "severity": _normalize_severity(item.get("severity")),
        "message": str(item.get("message") or item.get("observed") or category).strip(),
        "expected": item.get("expected", ""),
        "observed": item.get("observed", ""),
        "evidence": item.get("evidence", ""),
        "review_item_index": index,
    }


def _normalize_status(value: Any) -> str:
    normalized = str(value or "review").strip().casefold()
    return normalized if normalized in {"pass", "review", "fail"} else "review"


def _worst_status(values: list[Any]) -> str:
    rank = {"pass": 0, "review": 1, "fail": 2}
    normalized = [_normalize_status(value) for value in values]
    return max(normalized, key=lambda value: rank[value], default="review")


def _normalize_severity(value: Any) -> str:
    normalized = str(value or "P3").strip().upper()
    return normalized if normalized in SEVERITY_RANK else "P3"


def _max_severity(values: list[str]) -> str:
    if not values:
        return "P3"
    return max(values, key=lambda severity: SEVERITY_RANK.get(severity, 0))


def _clamp_float(value: Any, min_value: float, max_value: float, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, number))


def _normalize_score_breakdown(value: Any, review_items: list[dict[str, Any]]) -> dict[str, int]:
    keys = ("text_accuracy", "product_consistency", "layout_stability", "brand_compliance")
    if isinstance(value, dict):
        normalized = {
            key: int(round(_clamp_float(value.get(key), 0.0, 100.0, default=0.0)))
            for key in keys
        }
        if any(normalized.values()):
            return normalized

    derived = {key: 95 for key in keys}
    category_keys = {
        "text_accuracy": ("text_accuracy",),
        "product_consistency": ("reference_consistency", "visual_quality"),
        "layout_stability": ("layout_position",),
        "brand_compliance": ("brand_compliance", "prompt_following"),
    }
    for item in review_items:
        result = str(item.get("result") or "review")
        deduction = 35 if result == "fail" else 14 if result == "review" else 0
        category = str(item.get("category") or "other")
        for score_key, categories in category_keys.items():
            if category in categories:
                derived[score_key] = max(0, derived[score_key] - deduction)
    return derived


def _target_region_from_visual_review(visual_review: dict[str, Any]) -> tuple[float, float, float, float] | None:
    if not isinstance(visual_review, dict):
        return None
    return parse_bbox(visual_review.get("target_region"))


def _lines_inside_region(
    lines: list[dict[str, Any]],
    region: tuple[float, float, float, float] | None,
) -> list[dict[str, Any]]:
    if region is None:
        return []
    return [line for line in lines if _line_center_inside_region(line, region)]


def _lines_outside_region(
    lines: list[dict[str, Any]],
    region: tuple[float, float, float, float] | None,
) -> list[dict[str, Any]]:
    if region is None:
        return []
    return [line for line in lines if not _line_center_inside_region(line, region)]


def _line_center_inside_region(line: dict[str, Any], region: tuple[float, float, float, float]) -> bool:
    bbox = parse_bbox(line.get("bbox"))
    return bool(bbox and bbox_center_inside_region(bbox, region))
