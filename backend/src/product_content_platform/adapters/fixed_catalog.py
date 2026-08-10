from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from product_content_platform.domain import DomainValidationError, image_capabilities, validate_image_size


_DEFAULT_SIZE = "2048x2048"


class FixedContentCatalog:
    """Small template catalog with built-in layouts and persisted user-created variants."""

    _defaults: tuple[dict[str, Any], ...] = (
        {
            "id": "hero-center",
            "name": "主视觉居中",
            "page_types": ["hero"],
            "layout": "center",
            "safe_area": 0.08,
            "text_box": [0.09, 0.07, 0.91, 0.29],
            "product_box": [0.20, 0.32, 0.80, 0.94],
            "product_anchor_box": [0.24, 0.34, 0.76, 0.92],
            "composition_instruction": "顶部 7%-29% 保持纯净低细节留白；商品主体完整居中放在下方 32%-94%，四周保留边距",
            "scene_prompt_hint": "营造完整的高端家居或建筑空间，使用自然光、真实材质、地面投影和少量辅助陈设丰富画面",
        },
        {
            "id": "split-left",
            "name": "左文右图",
            "page_types": ["selling_point", "function"],
            "layout": "split_left",
            "safe_area": 0.07,
            "text_box": [0.07, 0.11, 0.43, 0.82],
            "product_box": [0.48, 0.16, 0.94, 0.94],
            "product_anchor_box": [0.52, 0.20, 0.92, 0.92],
            "composition_instruction": "左侧 7%-43% 保持纯净低细节留白；商品主体完整放在右侧 48%-94%，不要进入左侧留白区",
            "scene_prompt_hint": "使用右侧主商品、左侧负空间的广告摄影构图，背景可以有墙面、地面、柔和光影和克制的生活陈设",
        },
        {
            "id": "split-right",
            "name": "左图右文",
            "page_types": ["selling_point", "function"],
            "layout": "split_right",
            "safe_area": 0.07,
            "text_box": [0.57, 0.11, 0.93, 0.82],
            "product_box": [0.06, 0.16, 0.52, 0.94],
            "product_anchor_box": [0.08, 0.20, 0.48, 0.92],
            "composition_instruction": "右侧 57%-93% 保持纯净低细节留白；商品主体完整放在左侧 6%-52%，不要进入右侧留白区",
            "scene_prompt_hint": "使用左侧主商品、右侧负空间的广告摄影构图，背景可以有墙面、地面、柔和光影和克制的生活陈设",
        },
        {
            "id": "scene-overlay",
            "name": "生活场景留白",
            "page_types": ["scene"],
            "layout": "overlay",
            "safe_area": 0.10,
            "text_box": [0.07, 0.08, 0.44, 0.28],
            "product_box": [0.14, 0.30, 0.94, 0.95],
            "product_anchor_box": [0.47, 0.30, 0.94, 0.94],
            "composition_instruction": "左上 7%-44%、顶部 8%-28% 保持安静低对比留白；商品主机的视觉重心放在右下 47%-94%、30%-94%，开门等延展结构可进入 14%-47% 的左下区域，但不得进入左上文字留白区，完整商品保持在画布内",
            "scene_prompt_hint": "生成可感知的真实生活空间，包含建筑环境、自然光、材质层次和与品类有关的辅助物件，但不要让装饰抢过商品主体",
        },
        {
            "id": "data-grid",
            "name": "参数信息",
            "page_types": ["parameters"],
            "layout": "grid",
            "safe_area": 0.08,
            "text_box": [0.07, 0.08, 0.93, 0.34],
            "product_box": [0.20, 0.38, 0.80, 0.94],
            "product_anchor_box": [0.24, 0.40, 0.76, 0.92],
            "composition_instruction": "顶部 7%-93%、8%-34% 保持纯净低细节留白；商品主体完整放在下方中央 20%-80%、38%-94%",
            "scene_prompt_hint": "使用精致的产品摄影或材质展台环境，加入柔和渐变、结构光和地面阴影，顶部保持清晰的信息留白",
        },
    )

    def __init__(self, storage_path: Path | None = None) -> None:
        self._storage_path = storage_path
        self._custom_templates = self._load_custom_templates()

    def templates(self) -> list[dict[str, Any]]:
        return [self._public_template(item) for item in (*self._defaults, *self._custom_templates)]

    def template(self, template_id: str) -> dict[str, Any]:
        item = next(
            (row for row in (*self._defaults, *self._custom_templates) if row["id"] == template_id),
            None,
        )
        if item is None:
            raise DomainValidationError(f"未知模板: {template_id}")
        return self._public_template(item)

    def create_template(
        self,
        *,
        name: str,
        page_types: list[str],
        base_template_id: str,
        size: str,
    ) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise DomainValidationError("模板名称不能为空")
        clean_page_types = list(dict.fromkeys(value.strip() for value in page_types if value.strip()))
        if not clean_page_types:
            raise DomainValidationError("模板至少需要一个适用页面类型")
        unknown_page_types = sorted(
            set(clean_page_types) - {"hero", "selling_point", "function", "scene", "parameters"}
        )
        if unknown_page_types:
            raise DomainValidationError(f"未知页面类型: {', '.join(unknown_page_types)}")
        width, height = validate_image_size(size)
        base = self.template(base_template_id)
        item = {
            **base,
            "id": str(uuid4()),
            "name": clean_name,
            "page_types": clean_page_types,
            "width": width,
            "height": height,
            "size": f"{width}x{height}",
            "is_builtin": False,
            "base_template_id": base_template_id,
        }
        self._custom_templates.append(item)
        self._persist()
        return self._public_template(item)

    def capabilities(self) -> dict[str, Any]:
        return image_capabilities()

    def _load_custom_templates(self) -> list[dict[str, Any]]:
        if self._storage_path is None or not self._storage_path.exists():
            return []
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        loaded: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                width, height = validate_image_size(str(item.get("size", "")))
            except DomainValidationError:
                continue
            loaded.append({**item, "width": width, "height": height, "is_builtin": False})
        return loaded

    def _persist(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._storage_path.write_text(
            json.dumps(self._custom_templates, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _public_template(item: dict[str, Any]) -> dict[str, Any]:
        width = int(item.get("width", 2048))
        height = int(item.get("height", 2048))
        return {
            **item,
            "page_types": list(item["page_types"]),
            "text_box": list(item["text_box"]),
            "product_box": list(item["product_box"]),
            "product_anchor_box": list(item.get("product_anchor_box") or item["product_box"]),
            "width": width,
            "height": height,
            "size": str(item.get("size") or f"{width}x{height}" or _DEFAULT_SIZE),
            "is_builtin": bool(item.get("is_builtin", True)),
        }

    def recipes(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "commerce-detail-v1",
                "name": "家电电商详情基础配方",
                "status": "published",
                "version": 1,
                "page_types": ["hero", "selling_point", "function", "scene", "parameters"],
                "candidate_count": 2,
                "qa_policy": "commerce-basic-v1",
            }
        ]
