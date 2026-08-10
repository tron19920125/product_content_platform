from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from product_content_platform.quality.llm_reviewer import TokenProvider, call_azure_chat_review, image_content_part
from product_content_platform.quality.llm_reviewer import LLM_REQUEST_MAX_ATTEMPTS
from product_content_platform.quality.review_requirements import build_review_requirements
from product_content_platform.quality.text_review import parse_bbox


PlanClient = Callable[[list[dict[str, Any]]], dict[str, Any] | str]


@dataclass(frozen=True)
class ReviewPlan:
    mode: str
    summary: str
    edit_target: str
    must_appear: list[str] = field(default_factory=list)
    must_not_appear: list[str] = field(default_factory=list)
    must_preserve: list[str] = field(default_factory=list)
    review_checks: list[str] = field(default_factory=list)
    target_hint: str = ""
    target_region: tuple[float, float, float, float] | None = None
    source: str = "llm"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "mode": self.mode,
            "summary": self.summary,
            "edit_target": self.edit_target,
            "must_appear": self.must_appear,
            "must_not_appear": self.must_not_appear,
            "must_preserve": self.must_preserve,
            "review_checks": self.review_checks,
            "target_hint": self.target_hint,
            "target_region": self.target_region,
            "source": self.source,
        }
        payload["requirements"] = build_review_requirements(payload)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, source: str | None = None) -> ReviewPlan:
        mode = str(payload.get("mode") or "edit").strip().casefold()
        if mode not in {"edit", "generate", "review", "replace_product"}:
            mode = "edit"
        return cls(
            mode=mode,
            summary=str(payload.get("summary") or "").strip(),
            edit_target=str(payload.get("edit_target") or "").strip(),
            must_appear=_string_list(payload.get("must_appear")),
            must_not_appear=_string_list(payload.get("must_not_appear")),
            must_preserve=_string_list(payload.get("must_preserve")),
            review_checks=_string_list(payload.get("review_checks")),
            target_hint=str(payload.get("target_hint") or "").strip(),
            target_region=parse_bbox(payload.get("target_region")),
            source=source or str(payload.get("source") or "llm").strip(),
        )


def build_review_plan_messages(
    prompt: str,
    *,
    mode: str,
    reference_ocr_lines: list[dict[str, Any]] | None = None,
    source_image_path: str = "",
    product_reference_image_path: str = "",
) -> list[dict[str, Any]]:
    input_payload = {
        "mode": mode,
        "user_prompt": prompt,
        "reference_ocr_lines": reference_ocr_lines or [],
    }
    output_schema = {
        "mode": "edit | generate | review | replace_product",
        "summary": "用中文概括任务和验收目标",
        "edit_target": "用中文说明主要生成或编辑目标",
        "must_appear": ["必须出现的文字、数字、物体或视觉要求"],
        "must_not_appear": ["必须删除或禁止出现的内容"],
        "must_preserve": ["编辑时必须保持不变的内容"],
        "review_checks": ["需要启用的审查项及重点"],
        "target_hint": "目标区域或相对位置的中文说明，没有则为空字符串",
        "target_region": ["归一化 x1", "归一化 y1", "归一化 x2", "归一化 y2"],
    }
    user_text = (
        f"请根据以下输入生成审查计划：\n{json.dumps(input_payload, ensure_ascii=False, indent=2)}\n\n"
        f"返回结构必须为：\n{json.dumps(output_schema, ensure_ascii=False, indent=2)}"
    )
    user_content: str | list[dict[str, Any]] = user_text
    source_image = image_content_part(source_image_path)
    product_reference = image_content_part(product_reference_image_path)
    if source_image or product_reference:
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        if source_image:
            content_parts.extend([{"type": "text", "text": "需要编辑的原切片："}, source_image])
        if product_reference:
            content_parts.extend([{"type": "text", "text": "目标产品参考图："}, product_reference])
        user_content = content_parts
    return [
        {
            "role": "system",
            "content": (
                "你是图像生成与编辑系统中的需求理解 Agent。你的职责是把用户自然语言需求转换成"
                "结构化审查计划，不负责直接判断图片是否合格。必须从用户提示词和参考图 OCR 中提取"
                "明确要求，区分必须出现、必须删除、必须保留和重点检查。涉及文字、数字、单位、型号、"
                "价格和位置时要精确保留原文。编辑任务默认保留用户未要求修改的商品主体、品牌标识、"
                "构图、背景和非目标区域，但不要虚构用户未提供的商品参数。所有自然语言字段使用中文。"
                "当 mode=replace_product 时，必须同时观察原切片和目标产品参考图：原切片决定产品区域、"
                "位置、大小、角度、透视、遮挡和所有非产品内容；目标产品图决定颜色、材质、门体、控制"
                "面板、Logo位置和关键结构。target_region 必须返回原切片中待替换产品的归一化边界框。"
                "must_preserve 必须覆盖原切片文字、版式、背景和非产品区域；review_checks 必须覆盖目标"
                "产品外观一致性、产品几何稳定、遮挡关系和非产品区域稳定。"
                "只返回有效 JSON。"
            ),
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]


def create_review_plan(
    prompt: str,
    *,
    mode: str,
    reference_ocr_lines: list[dict[str, Any]] | None = None,
    source_image_path: str = "",
    product_reference_image_path: str = "",
    client: PlanClient | None = None,
    bearer_token: str | None = None,
    api_key: str | None = None,
    endpoint: str | None = None,
    timeout: int = 120,
    max_attempts: int = LLM_REQUEST_MAX_ATTEMPTS,
    token_provider: TokenProvider | None = None,
) -> ReviewPlan:
    messages = build_review_plan_messages(
        prompt,
        mode=mode,
        reference_ocr_lines=reference_ocr_lines,
        source_image_path=source_image_path,
        product_reference_image_path=product_reference_image_path,
    )
    response = client(messages) if client else call_azure_chat_review(
        messages,
        bearer_token=bearer_token,
        api_key=api_key,
        endpoint=endpoint,
        timeout=timeout,
        max_attempts=max_attempts,
        token_provider=token_provider,
    )
    return parse_review_plan_response(response, mode=mode)


def parse_review_plan_response(response: dict[str, Any] | str, *, mode: str) -> ReviewPlan:
    if isinstance(response, dict):
        payload = response
    else:
        payload = json.loads(_extract_json_object(response))
    payload = dict(payload)
    payload["mode"] = mode
    return ReviewPlan.from_dict(payload, source="llm")


def fallback_review_plan(prompt: str, *, mode: str) -> ReviewPlan:
    action = {
        "edit": "根据用户需求编辑参考图",
        "generate": "根据用户需求生成图片",
        "review": "根据用户要求审查已有图片",
        "replace_product": "将原切片中的产品替换为目标产品，并保持其他内容稳定",
    }.get(mode, "根据用户需求处理图片")
    replacement_mode = mode == "replace_product"
    return ReviewPlan(
        mode=mode,
        summary=prompt.strip()[:240],
        edit_target=action,
        must_preserve=(
            [
                "原切片产品区域之外的全部文字、数字、Logo、图标和版式",
                "背景、人物、家具、光效和其他非产品区域",
                "原产品的位置、大小、角度、透视和遮挡关系",
            ]
            if replacement_mode
            else ["用户未要求修改的商品主体、品牌标识、构图、背景和非目标区域"]
            if mode == "edit"
            else []
        ),
        review_checks=(
            ["目标产品外观一致性", "产品几何稳定", "非产品区域稳定", "文字与数字保持", "视觉融合质量"]
            if replacement_mode
            else ["提示词符合度", "文字与数字准确性", "视觉质量", "内容安全"]
        ),
        source="fallback",
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    raise ValueError("Review-plan response did not contain a JSON object.")
