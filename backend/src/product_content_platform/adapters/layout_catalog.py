from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from product_content_platform.domain import DomainValidationError, image_capabilities, validate_image_size


Box = list[float]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _box(value: Iterable[float], field: str) -> Box:
    result = [round(float(part), 6) for part in value]
    if len(result) != 4:
        raise DomainValidationError(f"{field} 必须包含四个坐标")
    x1, y1, x2, y2 = result
    if not all(0 <= part <= 1 for part in result) or x1 >= x2 or y1 >= y2:
        raise DomainValidationError(f"{field} 必须是画布内有效的 0-1 比例坐标")
    return result


def _contains(outer: Box, inner: Box) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _union(first: Box, second: Box) -> Box:
    return [min(first[0], second[0]), min(first[1], second[1]), max(first[2], second[2]), max(first[3], second[3])]


def _union_all(boxes: Iterable[Box]) -> Box:
    rows = list(boxes)
    if not rows:
        return [0.08, 0.08, 0.52, 0.38]
    result = list(rows[0])
    for box in rows[1:]:
        result = _union(result, box)
    return result


def _text_slot(value: dict[str, Any], index: int) -> dict[str, Any]:
    role = str(value.get("role") or "custom").strip().lower()
    if role not in {"headline", "body", "badge", "caption", "custom"}:
        raise DomainValidationError(f"text_slots[{index}].role 无效")
    slot_id = str(value.get("id") or f"text-{index + 1}").strip()
    if not slot_id:
        raise DomainValidationError(f"text_slots[{index}].id 不能为空")
    max_lines = int(value.get("max_lines", 2 if role == "headline" else 4))
    if not 1 <= max_lines <= 20:
        raise DomainValidationError(f"text_slots[{index}].max_lines 必须在 1-20 之间")
    return {
        "id": slot_id,
        "role": role,
        "name": str(value.get("name") or {"headline": "标题", "body": "正文", "badge": "标签", "caption": "说明"}.get(role, "文本框")).strip(),
        "box": _box(value.get("box") or [0.08, 0.08, 0.52, 0.20], f"text_slots[{index}].box"),
        "required": bool(value.get("required", role in {"headline", "body"})),
        "max_lines": max_lines,
        "default_style": dict(value.get("default_style") or {}),
    }


def _text_slots(values: Iterable[dict[str, Any]] | None, title_box: Box, body_box: Box) -> list[dict[str, Any]]:
    if values is None:
        values = (
            {"id": "headline", "role": "headline", "name": "标题", "box": title_box, "required": True, "max_lines": 2},
            {"id": "body", "role": "body", "name": "正文", "box": body_box, "required": True, "max_lines": 4},
        )
    rows = [_text_slot(dict(value), index) for index, value in enumerate(values)]
    if not rows:
        raise DomainValidationError("模板至少需要一个文字预留框")
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise DomainValidationError("文字预留框 id 不能重复")
    return rows


def _feature_slot(value: dict[str, Any], index: int) -> dict[str, Any]:
    slot_id = str(value.get("id") or f"feature-group-{index + 1}").strip()
    if not slot_id:
        raise DomainValidationError(f"feature_slots[{index}].id 不能为空")
    layout = str(value.get("layout") or "row").strip().lower()
    if layout not in {"row", "column", "grid"}:
        raise DomainValidationError(f"feature_slots[{index}].layout 无效")
    icon_position = str(value.get("icon_position") or "top").strip().lower()
    if icon_position not in {"top", "left"}:
        raise DomainValidationError(f"feature_slots[{index}].icon_position 无效")
    min_items = int(value.get("min_items", 2))
    max_items = int(value.get("max_items", 3))
    if not 1 <= min_items <= max_items <= 6:
        raise DomainValidationError(f"feature_slots[{index}] 的数量范围必须位于 1-6")
    columns = int(value.get("columns", min(3, max_items)))
    if not 1 <= columns <= 6:
        raise DomainValidationError(f"feature_slots[{index}].columns 必须位于 1-6")
    return {
        "id": slot_id,
        "name": str(value.get("name") or "图文卖点组").strip() or "图文卖点组",
        "box": _box(value.get("box") or [0.08, 0.55, 0.52, 0.88], f"feature_slots[{index}].box"),
        "layout": layout,
        "columns": columns,
        "min_items": min_items,
        "max_items": max_items,
        "icon_position": icon_position,
        "icon_scale": max(0.1, min(0.8, float(value.get("icon_scale", 0.28)))),
        "item_gap": max(0.0, min(0.2, float(value.get("item_gap", 0.025)))),
        "icon_text_gap": max(0.0, min(0.2, float(value.get("icon_text_gap", 0.012)))),
        "card_style": dict(value.get("card_style") or {}),
        "title_style": dict(value.get("title_style") or {}),
        "description_style": dict(value.get("description_style") or {}),
    }


def _feature_slots(values: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows = [_feature_slot(dict(value), index) for index, value in enumerate(values or ())]
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise DomainValidationError("图文卖点预留区 id 不能重复")
    if len(rows) > 3:
        raise DomainValidationError("单个模板最多支持 3 个图文卖点预留区")
    return rows


def _legacy_text_boxes(slots: list[dict[str, Any]]) -> tuple[Box, Box]:
    headline = next((slot["box"] for slot in slots if slot["role"] == "headline"), slots[0]["box"])
    body = next((slot["box"] for slot in slots if slot["role"] == "body"), headline)
    return list(headline), list(body)


def _percent(value: float) -> int:
    return round(value * 100)


def _composition_instruction(
    text_slots: list[dict[str, Any]], feature_slots: list[dict[str, Any]],
    product_box: Box, product_anchor_box: Box,
) -> str:
    text_box = _union_all(slot["box"] for slot in text_slots)
    reservations = [slot["box"] for slot in text_slots] + [slot["box"] for slot in feature_slots]
    reserved_box = _union_all(reservations)
    feature_instruction = ""
    if feature_slots:
        areas = "；".join(
            f"{slot['name']}位于横向 {_percent(slot['box'][0])}%-{_percent(slot['box'][2])}%、纵向 "
            f"{_percent(slot['box'][1])}%-{_percent(slot['box'][3])}%"
            for slot in feature_slots
        )
        feature_instruction = f"；{areas}，这些区域用于后期叠加透明图标与可编辑文案，底图中不得生成图标、文字或卡片占位符"
    return (
        f"在画面横向 {_percent(text_box[0])}%-{_percent(text_box[2])}%、纵向 "
        f"{_percent(text_box[1])}%-{_percent(text_box[3])}% 保持干净低细节留白；"
        f"全部后期图层预留范围为横向 {_percent(reserved_box[0])}%-{_percent(reserved_box[2])}%、纵向 "
        f"{_percent(reserved_box[1])}%-{_percent(reserved_box[3])}%{feature_instruction}；"
        f"商品视觉重心放在横向 {_percent(product_anchor_box[0])}%-{_percent(product_anchor_box[2])}%、纵向 "
        f"{_percent(product_anchor_box[1])}%-{_percent(product_anchor_box[3])}%，完整商品及延展结构不得超出横向 "
        f"{_percent(product_box[0])}%-{_percent(product_box[2])}%、纵向 {_percent(product_box[1])}%-{_percent(product_box[3])}%"
    )


def _template(
    *,
    template_id: str,
    template_key: str,
    library_id: str,
    name: str,
    page_types: list[str],
    layout: str,
    title_box: Box,
    body_box: Box,
    product_box: Box,
    product_anchor_box: Box,
    safe_area_box: Box,
    scene_prompt_hint: str,
    text_slots: list[dict[str, Any]] | None = None,
    feature_slots: list[dict[str, Any]] | None = None,
    version: int = 1,
    status: str = "published",
    is_builtin: bool = True,
    base_template_id: str = "",
) -> dict[str, Any]:
    timestamp = _now()
    normalized_slots = _text_slots(text_slots, title_box, body_box)
    normalized_feature_slots = _feature_slots(feature_slots)
    title_box, body_box = _legacy_text_boxes(normalized_slots)
    return {
        "id": template_id,
        "template_key": template_key,
        "library_id": library_id,
        "name": name,
        "page_types": page_types,
        "layout": layout,
        "safe_area": round(safe_area_box[0], 4),
        "safe_area_box": safe_area_box,
        "title_box": title_box,
        "body_box": body_box,
        "text_slots": normalized_slots,
        "feature_slots": normalized_feature_slots,
        "text_box": _union_all(slot["box"] for slot in normalized_slots),
        "product_box": product_box,
        "product_anchor_box": product_anchor_box,
        "composition_instruction": _composition_instruction(normalized_slots, normalized_feature_slots, product_box, product_anchor_box),
        "scene_prompt_hint": scene_prompt_hint,
        "typography": {
            "font_family": "system_sans",
            "title_color": "",
            "body_color": "",
            "title_font_size": None,
            "body_font_size": None,
            "title_align": "left",
            "body_align": "left",
        },
        "version": version,
        "status": status,
        "is_builtin": is_builtin,
        "base_template_id": base_template_id,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


_DEFAULT_LIBRARIES: tuple[dict[str, Any], ...] = (
    {
        "id": "library-square-2048",
        "name": "2048 正方形基础版式库",
        "description": "适合电商主图、卖点、功能、场景和参数页的正方形基础版式。",
        "width": 2048,
        "height": 2048,
        "size": "2048x2048",
        "tags": ["正方形", "基础", "电商详情"],
        "status": "published",
        "is_builtin": True,
    },
    {
        "id": "library-landscape-3840",
        "name": "3840×2160 横版叙事版式库",
        "description": "最大横版画布，适合空间叙事、横幅广告和大场景商品展示。",
        "width": 3840,
        "height": 2160,
        "size": "3840x2160",
        "tags": ["横版", "4K", "场景叙事"],
        "status": "published",
        "is_builtin": True,
    },
    {
        "id": "library-portrait-3840",
        "name": "2160×3840 竖版故事版式库",
        "description": "最大竖版画布，适合移动端长屏、海报和纵向故事内容。",
        "width": 2160,
        "height": 3840,
        "size": "2160x3840",
        "tags": ["竖版", "4K", "移动端"],
        "status": "published",
        "is_builtin": True,
    },
)


_DEFAULT_TEMPLATES: tuple[dict[str, Any], ...] = (
    _template(
        template_id="hero-center", template_key="hero-center", library_id="library-square-2048",
        name="主视觉居中", page_types=["hero"], layout="center",
        title_box=[.09, .07, .91, .18], body_box=[.09, .19, .91, .29],
        product_box=[.20, .32, .80, .94], product_anchor_box=[.24, .34, .76, .92], safe_area_box=[.065, .055, .935, .945],
        scene_prompt_hint="营造完整的高端家居或建筑空间，使用自然光、真实材质、地面投影和少量辅助陈设丰富画面",
    ),
    _template(
        template_id="split-left", template_key="split-left", library_id="library-square-2048",
        name="左文右图", page_types=["selling_point", "function"], layout="split_left",
        title_box=[.07, .11, .43, .31], body_box=[.07, .34, .43, .82],
        product_box=[.48, .16, .94, .94], product_anchor_box=[.52, .20, .92, .92], safe_area_box=[.065, .055, .935, .945],
        scene_prompt_hint="使用右侧主商品、左侧负空间的广告摄影构图，加入墙面、地面、柔和光影和克制生活陈设",
    ),
    _template(
        template_id="split-right", template_key="split-right", library_id="library-square-2048",
        name="左图右文", page_types=["selling_point", "function"], layout="split_right",
        title_box=[.57, .11, .93, .31], body_box=[.57, .34, .93, .82],
        product_box=[.06, .16, .52, .94], product_anchor_box=[.08, .20, .48, .92], safe_area_box=[.065, .055, .935, .945],
        scene_prompt_hint="使用左侧主商品、右侧负空间的广告摄影构图，加入墙面、地面、柔和光影和克制生活陈设",
    ),
    _template(
        template_id="scene-overlay", template_key="scene-overlay", library_id="library-square-2048",
        name="生活场景留白", page_types=["scene"], layout="overlay",
        title_box=[.07, .08, .44, .17], body_box=[.07, .18, .44, .28],
        product_box=[.14, .30, .94, .95], product_anchor_box=[.47, .30, .94, .94], safe_area_box=[.065, .055, .935, .945],
        scene_prompt_hint="生成可感知的真实生活空间，包含建筑环境、自然光、材质层次和与品类有关的辅助物件",
    ),
    _template(
        template_id="data-grid", template_key="data-grid", library_id="library-square-2048",
        name="参数信息", page_types=["parameters"], layout="grid",
        title_box=[.07, .08, .93, .18], body_box=[.07, .20, .93, .34],
        product_box=[.20, .38, .80, .94], product_anchor_box=[.24, .40, .76, .92], safe_area_box=[.065, .055, .935, .945],
        scene_prompt_hint="使用精致产品摄影或材质展台环境，加入柔和渐变、结构光和地面阴影",
    ),
    _template(
        template_id="landscape-story-left-v1", template_key="landscape-story-left", library_id="library-landscape-3840",
        name="横版空间叙事", page_types=["hero", "scene"], layout="landscape_story_left",
        title_box=[.055, .12, .36, .28], body_box=[.055, .31, .34, .53],
        product_box=[.40, .08, .96, .94], product_anchor_box=[.56, .18, .91, .90], safe_area_box=[.035, .06, .965, .94],
        scene_prompt_hint="生成宽银幕高端洗护空间：左侧以安静建筑留白和材质层次承载信息，右侧商品处于自然侧光中，远景包含窗景、墙面与地面延伸",
    ),
    _template(
        template_id="landscape-feature-band-v1", template_key="landscape-feature-band", library_id="library-landscape-3840",
        name="横版功能展台", page_types=["selling_point", "function"], layout="landscape_feature_band",
        title_box=[.08, .08, .52, .20], body_box=[.08, .22, .43, .36],
        product_box=[.12, .35, .92, .95], product_anchor_box=[.54, .38, .86, .92], safe_area_box=[.035, .06, .965, .94],
        scene_prompt_hint="使用横向延伸的精品展台、克制的功能可视化光效和深景空间，商品位于右下视觉重心，左上保留结构化信息区",
    ),
    _template(
        template_id="landscape-editorial-right-v1", template_key="landscape-editorial-right", library_id="library-landscape-3840",
        name="横版右文编辑页", page_types=["selling_point", "function", "parameters"], layout="landscape_editorial_right",
        title_box=[.66, .14, .94, .30], body_box=[.66, .34, .94, .62],
        product_box=[.04, .10, .62, .94], product_anchor_box=[.13, .18, .52, .91], safe_area_box=[.035, .06, .965, .94],
        scene_prompt_hint="采用杂志编辑式横版构图，左侧商品与真实材质环境形成完整画面，右侧保持低细节信息留白",
    ),
    _template(
        template_id="portrait-story-top-v1", template_key="portrait-story-top", library_id="library-portrait-3840",
        name="竖版顶部故事", page_types=["hero", "scene"], layout="portrait_story_top",
        title_box=[.08, .055, .92, .15], body_box=[.08, .165, .78, .25],
        product_box=[.05, .28, .95, .96], product_anchor_box=[.22, .42, .86, .93], safe_area_box=[.055, .035, .945, .965],
        scene_prompt_hint="生成适合移动端海报的纵向高端洗护空间，上方是柔和天光和安静墙面，下方通过纵深地面、绿植与材质细节承载完整商品",
    ),
    _template(
        template_id="portrait-feature-bottom-v1", template_key="portrait-feature-bottom", library_id="library-portrait-3840",
        name="竖版底部卖点", page_types=["selling_point", "function"], layout="portrait_feature_bottom",
        title_box=[.09, .70, .91, .80], body_box=[.09, .82, .78, .93],
        product_box=[.05, .05, .95, .67], product_anchor_box=[.18, .10, .82, .63], safe_area_box=[.055, .035, .945, .965],
        scene_prompt_hint="构建向上延伸的明亮建筑空间，商品在上半部被自然光勾勒，下方使用平静低细节的材质地面承载卖点文字",
    ),
    _template(
        template_id="portrait-detail-stack-v1", template_key="portrait-detail-stack", library_id="library-portrait-3840",
        name="竖版细节层叠", page_types=["function", "parameters"], layout="portrait_detail_stack",
        title_box=[.08, .07, .70, .15], body_box=[.08, .17, .70, .28],
        product_box=[.10, .32, .90, .95], product_anchor_box=[.22, .40, .80, .91], safe_area_box=[.055, .035, .945, .965],
        scene_prompt_hint="使用纵向层叠的材料、柔和灯带和局部功能氛围，顶部信息区简洁，商品下方有清晰接地阴影和空间层次",
    ),
)


class LayoutContentCatalog:
    """Versioned layout libraries and page templates with legacy-template compatibility."""

    def __init__(self, storage_path: Path | None = None) -> None:
        self._storage_path = storage_path
        self._libraries = [deepcopy(item) for item in _DEFAULT_LIBRARIES]
        self._templates = [deepcopy(item) for item in _DEFAULT_TEMPLATES]
        self._load()

    def capabilities(self) -> dict[str, Any]:
        return image_capabilities()

    def libraries(self) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for item in self._templates:
            if item.get("status") == "published":
                counts[item["library_id"]] = counts.get(item["library_id"], 0) + 1
        return [{**deepcopy(item), "template_count": counts.get(item["id"], 0)} for item in self._libraries]

    def library(self, library_id: str) -> dict[str, Any]:
        item = next((row for row in self._libraries if row["id"] == library_id), None)
        if item is None:
            raise DomainValidationError(f"未知版式库: {library_id}")
        result = deepcopy(item)
        result["template_count"] = len([row for row in self._templates if row["library_id"] == library_id and row.get("status") == "published"])
        return result

    def create_library(self, *, name: str, size: str, description: str = "", tags: list[str] | None = None) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise DomainValidationError("版式库名称不能为空")
        width, height = validate_image_size(size)
        timestamp = _now()
        item = {
            "id": str(uuid4()), "name": clean_name, "description": description.strip(),
            "width": width, "height": height, "size": f"{width}x{height}",
            "tags": list(dict.fromkeys(value.strip() for value in (tags or []) if value.strip())),
            "status": "draft", "is_builtin": False, "created_at": timestamp, "updated_at": timestamp,
        }
        self._libraries.append(item)
        self._persist()
        return {**deepcopy(item), "template_count": 0}

    def templates(self, *, library_id: str | None = None, include_drafts: bool = False) -> list[dict[str, Any]]:
        rows = self._templates
        if library_id:
            self.library(library_id)
            rows = [row for row in rows if row["library_id"] == library_id]
        if not include_drafts:
            rows = [row for row in rows if row.get("status", "published") == "published"]
        return [self._public_template(item) for item in rows]

    def template(self, template_id: str) -> dict[str, Any]:
        item = next((row for row in self._templates if row["id"] == template_id), None)
        if item is None:
            raise DomainValidationError(f"未知模板: {template_id}")
        return self._public_template(item)

    def create_template(
        self, *, name: str, page_types: list[str], base_template_id: str, size: str,
    ) -> dict[str, Any]:
        """Legacy API: clone a published template and publish it immediately."""
        width, height = validate_image_size(size)
        library = next((row for row in self._libraries if row["width"] == width and row["height"] == height), None)
        if library is None:
            library = self.create_library(name=f"{width}×{height} 自定义版式库", size=size)
            internal = next(row for row in self._libraries if row["id"] == library["id"])
            internal["status"] = "published"
        draft = self.create_template_draft(
            library_id=library["id"], name=name, page_types=page_types, base_template_id=base_template_id,
        )
        return self.publish_template(draft["id"])

    def create_template_draft(
        self,
        *,
        library_id: str,
        name: str,
        page_types: list[str],
        base_template_id: str = "",
        title_box: list[float] | None = None,
        body_box: list[float] | None = None,
        text_slots: list[dict[str, Any]] | None = None,
        feature_slots: list[dict[str, Any]] | None = None,
        product_box: list[float] | None = None,
        product_anchor_box: list[float] | None = None,
        safe_area_box: list[float] | None = None,
        scene_prompt_hint: str = "",
    ) -> dict[str, Any]:
        library = self.library(library_id)
        clean_name = name.strip()
        clean_page_types = list(dict.fromkeys(value.strip() for value in page_types if value.strip()))
        allowed = {"hero", "selling_point", "function", "scene", "parameters"}
        if not clean_name:
            raise DomainValidationError("模板名称不能为空")
        if not clean_page_types or set(clean_page_types) - allowed:
            raise DomainValidationError("模板至少需要一个有效的适用页面类型")
        base = self.template(base_template_id) if base_template_id else None
        default_title = [0.08, 0.08, 0.52, 0.20]
        default_body = [0.08, 0.23, 0.52, 0.38]
        default_product = [0.45, 0.18, 0.94, 0.94]
        default_anchor = [0.53, 0.24, 0.90, 0.90]
        item = _template(
            template_id=str(uuid4()), template_key=str(uuid4()), library_id=library_id,
            name=clean_name, page_types=clean_page_types, layout=str((base or {}).get("layout") or "custom"),
            title_box=_box(title_box or (base or {}).get("title_box") or default_title, "title_box"),
            body_box=_box(body_box or (base or {}).get("body_box") or default_body, "body_box"),
            text_slots=text_slots if text_slots is not None else (base or {}).get("text_slots"),
            feature_slots=feature_slots if feature_slots is not None else (base or {}).get("feature_slots"),
            product_box=_box(product_box or (base or {}).get("product_box") or default_product, "product_box"),
            product_anchor_box=_box(product_anchor_box or (base or {}).get("product_anchor_box") or default_anchor, "product_anchor_box"),
            safe_area_box=_box(safe_area_box or (base or {}).get("safe_area_box") or [.055, .045, .945, .955], "safe_area_box"),
            scene_prompt_hint=scene_prompt_hint.strip() or str((base or {}).get("scene_prompt_hint") or "生成具有真实空间层次、自然光和克制陈设的高端商品场景"),
            status="draft", is_builtin=False, base_template_id=base_template_id,
        )
        item["width"], item["height"], item["size"] = library["width"], library["height"], library["size"]
        self._validate_geometry(item)
        self._templates.append(item)
        self._persist()
        return self._public_template(item)

    def update_template_draft(self, template_id: str, **changes: Any) -> dict[str, Any]:
        item = next((row for row in self._templates if row["id"] == template_id), None)
        if item is None:
            raise DomainValidationError(f"未知模板: {template_id}")
        if item.get("status") != "draft":
            raise DomainValidationError("已发布模板不能原地修改，请先创建新版本")
        for field in ("title_box", "body_box", "product_box", "product_anchor_box", "safe_area_box"):
            if field in changes and changes[field] is not None:
                item[field] = _box(changes[field], field)
        if "text_slots" in changes and changes["text_slots"] is not None:
            item["text_slots"] = _text_slots(changes["text_slots"], item["title_box"], item["body_box"])
        elif "title_box" in changes or "body_box" in changes:
            item["text_slots"] = _text_slots(None, item["title_box"], item["body_box"])
        if "feature_slots" in changes and changes["feature_slots"] is not None:
            item["feature_slots"] = _feature_slots(changes["feature_slots"])
        if "name" in changes:
            clean_name = str(changes["name"]).strip()
            if not clean_name:
                raise DomainValidationError("模板名称不能为空")
            item["name"] = clean_name
        if "page_types" in changes:
            item["page_types"] = list(dict.fromkeys(str(value).strip() for value in changes["page_types"] if str(value).strip()))
        if "scene_prompt_hint" in changes:
            item["scene_prompt_hint"] = str(changes["scene_prompt_hint"]).strip()
        item["title_box"], item["body_box"] = _legacy_text_boxes(item["text_slots"])
        item["text_box"] = _union_all(slot["box"] for slot in item["text_slots"])
        item["safe_area"] = round(item["safe_area_box"][0], 4)
        item["composition_instruction"] = _composition_instruction(
            item["text_slots"], item.get("feature_slots") or [], item["product_box"], item["product_anchor_box"]
        )
        item["updated_at"] = _now()
        self._validate_geometry(item)
        self._persist()
        return self._public_template(item)

    def delete_template_draft(self, template_id: str) -> None:
        item = next((row for row in self._templates if row["id"] == template_id), None)
        if item is None:
            raise DomainValidationError(f"未知模板: {template_id}")
        if item.get("status") != "draft":
            raise DomainValidationError("只能删除尚未发布的模板草稿")
        self._templates = [row for row in self._templates if row["id"] != template_id]
        self._persist()

    def create_next_version(self, template_id: str) -> dict[str, Any]:
        source = self.template(template_id)
        if source.get("status") != "published":
            raise DomainValidationError("只有已发布模板可以创建新版本")
        version = max(int(row.get("version", 1)) for row in self._templates if row.get("template_key") == source["template_key"]) + 1
        item = deepcopy(source)
        item.update({"id": str(uuid4()), "version": version, "status": "draft", "is_builtin": False, "created_at": _now(), "updated_at": _now()})
        self._templates.append(item)
        self._persist()
        return self._public_template(item)

    def publish_template(self, template_id: str) -> dict[str, Any]:
        item = next((row for row in self._templates if row["id"] == template_id), None)
        if item is None:
            raise DomainValidationError(f"未知模板: {template_id}")
        if item.get("status") != "draft":
            return self._public_template(item)
        self._validate_geometry(item)
        item["status"] = "published"
        item["updated_at"] = _now()
        library = next(row for row in self._libraries if row["id"] == item["library_id"])
        if library.get("status") == "draft":
            library["status"] = "published"
            library["updated_at"] = _now()
        self._persist()
        return self._public_template(item)

    def _validate_geometry(self, item: dict[str, Any]) -> None:
        safe = item["safe_area_box"]
        if not all(_contains(safe, slot["box"]) for slot in item["text_slots"]):
            raise DomainValidationError("标题框和正文框必须位于安全区域内")
        if not all(_contains(safe, slot["box"]) for slot in item.get("feature_slots") or []):
            raise DomainValidationError("图文卖点预留区必须位于安全区域内")
        if not _contains(item["product_box"], item["product_anchor_box"]):
            raise DomainValidationError("商品核心区必须位于商品允许区域内")

    def _load(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(payload, list):
            self._migrate_legacy(payload)
            self._persist()
            return
        if not isinstance(payload, dict) or int(payload.get("schema_version", 0)) != 2:
            return
        for library in payload.get("libraries", []):
            if isinstance(library, dict) and library.get("id") not in {row["id"] for row in self._libraries}:
                try:
                    width, height = validate_image_size(str(library.get("size", "")))
                except DomainValidationError:
                    continue
                self._libraries.append({**library, "width": width, "height": height, "size": f"{width}x{height}", "is_builtin": False})
        for template in payload.get("templates", []):
            if isinstance(template, dict) and template.get("id") not in {row["id"] for row in self._templates}:
                try:
                    normalized = self._normalize_loaded_template(template)
                    self._validate_geometry(normalized)
                except (DomainValidationError, KeyError, TypeError, ValueError):
                    continue
                self._templates.append(normalized)

    def _migrate_legacy(self, rows: list[Any]) -> None:
        for source in rows:
            if not isinstance(source, dict) or not source.get("id"):
                continue
            try:
                width, height = validate_image_size(str(source.get("size", "")))
            except DomainValidationError:
                continue
            library = next((row for row in self._libraries if row["width"] == width and row["height"] == height), None)
            if library is None:
                timestamp = _now()
                library = {"id": str(uuid4()), "name": f"{width}×{height} 迁移版式库", "description": "由旧版自定义模板自动迁移", "width": width, "height": height, "size": f"{width}x{height}", "tags": ["迁移"], "status": "published", "is_builtin": False, "created_at": timestamp, "updated_at": timestamp}
                self._libraries.append(library)
            migrated = self._normalize_loaded_template({**source, "library_id": library["id"], "status": "published", "version": 1})
            self._templates.append(migrated)

    def _normalize_loaded_template(self, source: dict[str, Any]) -> dict[str, Any]:
        library = self.library(str(source["library_id"]))
        text = _box(source.get("text_box") or [.08, .08, .52, .38], "text_box")
        title = _box(source.get("title_box") or [text[0], text[1], text[2], text[1] + (text[3] - text[1]) * .42], "title_box")
        body = _box(source.get("body_box") or [text[0], text[1] + (text[3] - text[1]) * .48, text[2], text[3]], "body_box")
        safe = _box(source.get("safe_area_box") or [.055, .045, .945, .955], "safe_area_box")
        product = _box(source.get("product_box") or [.45, .18, .94, .94], "product_box")
        anchor = _box(source.get("product_anchor_box") or product, "product_anchor_box")
        slots = _text_slots(source.get("text_slots"), title, body)
        feature_slots = _feature_slots(source.get("feature_slots"))
        title, body = _legacy_text_boxes(slots)
        timestamp = str(source.get("created_at") or _now())
        return {
            **source,
            "template_key": str(source.get("template_key") or source["id"]),
            "library_id": library["id"],
            "width": library["width"], "height": library["height"], "size": library["size"],
            "title_box": title, "body_box": body, "text_slots": slots, "feature_slots": feature_slots,
            "text_box": _union_all(slot["box"] for slot in slots),
            "safe_area_box": safe, "safe_area": round(safe[0], 4),
            "product_box": product, "product_anchor_box": anchor,
            "composition_instruction": str(source.get("composition_instruction") or _composition_instruction(slots, feature_slots, product, anchor)),
            "scene_prompt_hint": str(source.get("scene_prompt_hint") or "生成具有真实空间层次、自然光和克制陈设的高端商品场景"),
            "typography": dict(source.get("typography") or {}),
            "version": int(source.get("version", 1)), "status": str(source.get("status") or "published"),
            "is_builtin": False, "created_at": timestamp, "updated_at": str(source.get("updated_at") or timestamp),
        }

    def _persist(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        custom_libraries = [row for row in self._libraries if not row.get("is_builtin")]
        custom_templates = [row for row in self._templates if not row.get("is_builtin")]
        self._storage_path.write_text(json.dumps({"schema_version": 2, "libraries": custom_libraries, "templates": custom_templates}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _public_template(self, item: dict[str, Any]) -> dict[str, Any]:
        library = self.library(item["library_id"])
        return {
            **deepcopy(item),
            "width": library["width"], "height": library["height"], "size": library["size"],
            "page_types": list(item["page_types"]),
            "title_box": list(item["title_box"]), "body_box": list(item["body_box"]), "text_box": list(item["text_box"]),
            "text_slots": deepcopy(item["text_slots"]),
            "feature_slots": deepcopy(item.get("feature_slots") or []),
            "safe_area_box": list(item["safe_area_box"]), "product_box": list(item["product_box"]), "product_anchor_box": list(item["product_anchor_box"]),
        }

    def recipes(self) -> list[dict[str, Any]]:
        return [{"id": "commerce-detail-v1", "name": "家电电商详情基础配方", "status": "published", "version": 1, "page_types": ["hero", "selling_point", "function", "scene", "parameters"], "candidate_count": 2, "qa_policy": "commerce-basic-v1"}]


FixedContentCatalog = LayoutContentCatalog
