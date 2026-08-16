from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from product_content_platform.domain import PageType, ProductProfile
from product_content_platform.integrations.azure_credentials import token_provider_from_env
from product_content_platform.quality.llm_reviewer import (
    LlmReviewerError,
    call_azure_chat_review,
    image_content_part,
)


class ContentPlanner:
    """Turns verified product facts and layout constraints into auditable page-copy suggestions."""

    def __init__(self, mode: str = "local") -> None:
        if mode not in {"local", "azure"}:
            raise ValueError("规划模式必须是 local 或 azure")
        self.mode = mode
        endpoint = os.environ.get("AZURE_OPENAI_REVIEW_ENDPOINT") or os.environ.get("AZURE_OPENAI_RESOURCE_ENDPOINT") or ""
        self._token_provider = token_provider_from_env(endpoint=endpoint) if mode == "azure" else None

    def create_suggestion(
        self,
        *,
        profile: ProductProfile,
        template_specs: list[dict[str, Any]],
        reference_paths: list[Path],
    ) -> dict[str, Any]:
        facts = self._facts(profile)
        fallback = self._fallback(profile, template_specs, facts)
        if self.mode != "azure":
            return fallback
        try:
            response = call_azure_chat_review(
                self._messages(profile, template_specs, facts, reference_paths),
                timeout=self._positive_int_env("PCP_LLM_PLANNING_TIMEOUT", 120),
                max_attempts=self._positive_int_env("PCP_LLM_PLANNING_MAX_ATTEMPTS", 3),
                token_provider=self._token_provider,
            )
            parsed = self._parse(response, profile, template_specs, facts, fallback)
            parsed["source"] = "azure-llm"
            parsed["degraded"] = False
            return parsed
        except Exception as exc:
            return {**fallback, "degraded": True, "error": str(exc)}

    @staticmethod
    def _facts(profile: ProductProfile) -> list[dict[str, str]]:
        rows = [
            {"id": "product.name", "label": "商品名称", "value": profile.name},
            {"id": "product.sku", "label": "SKU", "value": profile.sku},
            {"id": "product.category", "label": "品类", "value": profile.category},
        ]
        if profile.model:
            rows.append({"id": "product.model", "label": "型号", "value": profile.model})
        rows.extend(
            {"id": f"selling_point.{index}", "label": f"卖点 {index + 1}", "value": value}
            for index, value in enumerate(profile.selling_points)
        )
        rows.extend(
            {"id": f"parameter.{key}", "label": key, "value": value}
            for key, value in profile.parameters.items()
        )
        if profile.brand_requirements:
            rows.append({"id": "brand.requirements", "label": "品牌要求", "value": profile.brand_requirements})
        if profile.output_requirements:
            rows.append({"id": "output.requirements", "label": "输出要求", "value": profile.output_requirements})
        return rows

    def _messages(
        self,
        profile: ProductProfile,
        template_specs: list[dict[str, Any]],
        facts: list[dict[str, str]],
        reference_paths: list[Path],
    ) -> list[dict[str, Any]]:
        payload = {
            "product": {"name": profile.name, "category": profile.category},
            "verified_facts": facts,
            "pages": [
                {
                    "key": item["key"],
                    "page_type": item["page_type"],
                    "template_id": item["template_id"],
                    "template_name": item.get("template_name", ""),
                    "scene_prompt_hint": item.get("scene_prompt_hint", ""),
                    "composition_instruction": item.get("composition_instruction", ""),
                    "feature_slots": item.get("feature_slots", []),
                }
                for item in template_specs
            ],
        }
        schema = {
            "pages": [
                {
                    "key": "必须原样返回输入页 key",
                    "title": "简洁中文标题，建议 4-16 字",
                    "body": "中文正文，建议 12-60 字",
                    "visual_goal": "只描述场景、材质、光线、商品角度和效果，不包含要生成进底图的营销文字",
                    "feature_points": [
                        {
                            "id": "feature-1",
                            "title": "可编辑卖点短标题",
                            "description": "可编辑的一句说明",
                            "icon_concept": "不含文字、数字或 Logo 的透明图标视觉概念",
                            "fact_refs": ["该卖点实际使用的 verified_facts.id"],
                        }
                    ],
                    "fact_refs": ["该页文案实际使用的 verified_facts.id"],
                    "reasoning": "简述该页在整组内容中的职责",
                }
            ],
            "set_strategy": "概括整组页面的叙事顺序",
        }
        user_parts: list[dict[str, Any]] = [{
            "type": "text",
            "text": (
                f"请为以下商品和固定页面骨架生成可编辑的内容规划建议：\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
                f"严格返回 JSON：\n{json.dumps(schema, ensure_ascii=False, indent=2)}"
            ),
        }]
        for index, path in enumerate(reference_paths[:3], start=1):
            part = image_content_part(str(path))
            if part:
                user_parts.extend([{"type": "text", "text": f"可用于本次规划的商品参考图 {index}："}, part])
        return [
            {
                "role": "system",
                "content": (
                    "你是电商视觉内容规划师。只使用 verified_facts 中的已确认事实，不得虚构型号、数字、参数、认证、"
                    "价格或功效。每个输入页面必须且只能返回一项，key 必须原样保留。标题和正文是后期排版文案；"
                    "visual_goal 用于指导无营销文字底图生成，必须说明与模板留白兼容的场景和商品表现，不得要求模型生成"
                    "标题、正文、标语、数字标签或水印。fact_refs 只能引用实际使用过的事实 id。所有自然语言使用中文，只返回有效 JSON。"
                    "仅当页面包含 feature_slots 时返回 feature_points，数量必须符合预留区的 min_items/max_items；每个卖点必须有 fact_refs，"
                    "icon_concept 只描述可独立生成的无文字透明图标，不得要求图标携带字符。"
                ),
            },
            {"role": "user", "content": user_parts},
        ]

    def _parse(
        self,
        response: str | dict[str, Any],
        profile: ProductProfile,
        template_specs: list[dict[str, Any]],
        facts: list[dict[str, str]],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        payload = response if isinstance(response, dict) else json.loads(self._extract_json(response))
        rows = payload.get("pages")
        if not isinstance(rows, list):
            raise ValueError("LLM 规划结果缺少 pages 数组")
        returned = {str(item.get("key") or ""): item for item in rows if isinstance(item, dict)}
        fallback_rows = {item["key"]: item for item in fallback["pages"]}
        known_fact_ids = {item["id"] for item in facts}
        allowed_numbers = self._numbers(" ".join(item["value"] for item in facts))
        warnings: list[str] = []
        normalized: list[dict[str, Any]] = []
        for spec in template_specs:
            key = spec["key"]
            raw = returned.get(key)
            if raw is None:
                warnings.append(f"{key} 缺失，已使用确定性文案")
                normalized.append(fallback_rows[key])
                continue
            title = self._clean(raw.get("title"), 40)
            body = self._clean(raw.get("body"), 160)
            visual_goal = self._clean(raw.get("visual_goal"), 500)
            feature_points = self._normalize_feature_points(
                raw.get("feature_points"), spec, known_fact_ids, allowed_numbers,
                fallback_rows[key].get("feature_points") or [], warnings, key,
            )
            feature_copy = " ".join(
                f"{item['title']} {item['description']}" for item in feature_points
            )
            invented = sorted(self._numbers(f"{title} {body} {feature_copy}") - allowed_numbers)
            if not title or invented:
                warnings.append(f"{key} 含空标题或未确认数字 {', '.join(invented)}，已使用确定性文案")
                normalized.append(fallback_rows[key])
                continue
            normalized.append({
                "key": key,
                "page_type": spec["page_type"],
                "template_id": spec["template_id"],
                "title": title,
                "body": body,
                "visual_goal": visual_goal or fallback_rows[key]["visual_goal"],
                "feature_points": feature_points,
                "fact_refs": [value for value in self._string_list(raw.get("fact_refs")) if value in known_fact_ids],
                "reasoning": self._clean(raw.get("reasoning"), 200),
                "field_sources": {"title": "llm", "body": "llm", "visual_goal": "llm", "feature_points": "llm"},
            })
        return {
            "pages": normalized,
            "set_strategy": self._clean(payload.get("set_strategy"), 300),
            "facts": facts,
            "warnings": warnings,
        }

    def _fallback(
        self,
        profile: ProductProfile,
        template_specs: list[dict[str, Any]],
        facts: list[dict[str, str]],
    ) -> dict[str, Any]:
        points = list(profile.selling_points)
        first = points[0] if points else "专业呵护每一次使用"
        second = points[1] if len(points) > 1 else "智能科技带来省心体验"
        parameters = " · ".join(f"{key} {value}" for key, value in list(profile.parameters.items())[:4])
        content = {
            PageType.HERO.value: (profile.name, first, "清晰呈现完整商品与品牌气质，使用真实材质、自然光和克制留白"),
            PageType.SELLING_POINT.value: (first, f"围绕{first}说明核心价值", "突出与该卖点相关的商品细节或使用效果，并保持文字区低细节"),
            PageType.FUNCTION.value: (second, f"围绕{second}说明功能体验", "通过功能场景、材质反射或局部效果解释卖点，避免生成营销文字"),
            PageType.SCENE.value: ("融入理想生活", f"让{profile.name}自然融入目标用户的生活空间", "生成有建筑环境、光影和辅助陈设的完整生活场景，商品清晰可见"),
            PageType.PARAMETERS.value: ("关键参数", parameters or f"型号 {profile.model or profile.sku}", "使用精致展台、柔和渐变和结构光呈现商品，参数文字区域保持干净"),
        }
        pages = []
        for spec in template_specs:
            title, body, visual_goal = content.get(spec["page_type"], content[PageType.SELLING_POINT.value])
            pages.append({
                "key": spec["key"], "page_type": spec["page_type"], "template_id": spec["template_id"],
                "title": title, "body": body, "visual_goal": visual_goal,
                "feature_points": self._fallback_features(spec, facts),
                "fact_refs": self._fallback_fact_refs(spec["page_type"], facts),
                "reasoning": "确定性降级建议，确保在 LLM 不可用时仍可继续演示。",
                "field_sources": {"title": "deterministic", "body": "deterministic", "visual_goal": "deterministic", "feature_points": "deterministic"},
            })
        return {
            "pages": pages,
            "set_strategy": "从商品识别、核心卖点、功能体验、生活场景到已确认参数逐步展开。",
            "facts": facts,
            "warnings": [],
            "source": "deterministic-fallback",
            "degraded": self.mode == "azure",
        }

    @staticmethod
    def _fallback_fact_refs(page_type: str, facts: list[dict[str, str]]) -> list[str]:
        ids = [item["id"] for item in facts]
        if page_type == PageType.PARAMETERS.value:
            return [value for value in ids if value.startswith("parameter.") or value in {"product.model", "product.sku"}]
        if page_type in {PageType.SELLING_POINT.value, PageType.FUNCTION.value}:
            return [value for value in ids if value.startswith("selling_point.")][:1]
        return [value for value in ids if value == "product.name"]

    @classmethod
    def _fallback_features(cls, spec: dict[str, Any], facts: list[dict[str, str]]) -> list[dict[str, Any]]:
        slots = list(spec.get("feature_slots") or [])
        if not slots:
            return []
        limit = max(1, min(6, int(slots[0].get("max_items", 3))))
        candidates = [item for item in facts if item["id"].startswith("selling_point.")]
        candidates.extend(item for item in facts if item["id"].startswith("parameter."))
        result: list[dict[str, Any]] = []
        for index, fact in enumerate(candidates[:limit], start=1):
            is_parameter = fact["id"].startswith("parameter.")
            title = f"{fact['label']} {fact['value']}" if is_parameter else fact["value"]
            description = f"已确认的{fact['label']}信息" if is_parameter else f"围绕{fact['value']}呈现核心体验"
            result.append({
                "id": f"feature-{index}", "title": cls._clean(title, 40),
                "description": cls._clean(description, 120),
                "icon_concept": f"{fact['label']}的简洁线性图标，不含文字、数字或 Logo",
                "fact_refs": [fact["id"]],
            })
        minimum = max(1, min(6, int(slots[0].get("min_items", 1))))
        return result if len(result) >= minimum else []

    @classmethod
    def _normalize_feature_points(
        cls,
        value: Any,
        spec: dict[str, Any],
        known_fact_ids: set[str],
        allowed_numbers: set[str],
        fallback: list[dict[str, Any]],
        warnings: list[str],
        page_key: str,
    ) -> list[dict[str, Any]]:
        slots = list(spec.get("feature_slots") or [])
        if not slots:
            return []
        slot = slots[0]
        minimum = max(1, min(6, int(slot.get("min_items", 1))))
        maximum = max(minimum, min(6, int(slot.get("max_items", 3))))
        if not isinstance(value, list):
            warnings.append(f"{page_key} 缺少图文卖点，已使用确定性卖点")
            return list(fallback)
        rows: list[dict[str, Any]] = []
        for index, raw in enumerate(value[:maximum], start=1):
            if not isinstance(raw, dict):
                continue
            title = cls._clean(raw.get("title"), 40)
            description = cls._clean(raw.get("description"), 120)
            icon_concept = cls._clean(raw.get("icon_concept"), 120)
            fact_refs = [item for item in cls._string_list(raw.get("fact_refs")) if item in known_fact_ids]
            invented = cls._numbers(f"{title} {description}") - allowed_numbers
            if not title or not icon_concept or not fact_refs or invented:
                continue
            rows.append({
                "id": cls._clean(raw.get("id"), 64) or f"feature-{index}",
                "title": title, "description": description,
                "icon_concept": icon_concept, "fact_refs": fact_refs,
            })
        if len(rows) < minimum:
            warnings.append(f"{page_key} 的图文卖点缺少事实来源或数量不足，已使用确定性卖点")
            return list(fallback)
        return rows

    @staticmethod
    def _clean(value: Any, limit: int) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        return [str(item).strip() for item in value] if isinstance(value, list) else []

    @staticmethod
    def _numbers(value: str) -> set[str]:
        return set(re.findall(r"\d+(?:\.\d+)?", value))

    @staticmethod
    def _extract_json(value: str) -> str:
        stripped = value.strip()
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM 规划结果中没有 JSON 对象")
        return stripped[start : end + 1]

    @staticmethod
    def _positive_int_env(name: str, default: int) -> int:
        try:
            return max(1, int(os.environ.get(name, str(default))))
        except ValueError:
            return default
