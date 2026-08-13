from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .errors import DomainValidationError
from .models import utc_now


TEXT_ROLES = {"headline", "subheadline", "body", "badge", "price", "parameter", "caption", "disclaimer", "custom"}
TEXT_ALIGNMENTS = {"left", "center", "right"}
VERTICAL_ALIGNMENTS = {"top", "center", "bottom"}
FONT_STYLES = {"normal", "italic"}


def _box(value: Any) -> tuple[float, float, float, float]:
    try:
        result = tuple(round(float(part), 6) for part in value)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError("文字图层坐标必须是 0-1 比例数字") from exc
    if len(result) != 4:
        raise DomainValidationError("文字图层坐标必须包含四个值")
    x1, y1, x2, y2 = result
    if not all(0 <= part <= 1 for part in result) or x1 >= x2 or y1 >= y2:
        raise DomainValidationError("文字图层必须位于画布内且宽高大于 0")
    return result  # type: ignore[return-value]


def _color(value: Any, fallback: str) -> str:
    clean = str(value or fallback).upper()
    if not re.fullmatch(r"#[0-9A-F]{6}", clean):
        raise DomainValidationError("文字颜色必须使用 #RRGGBB")
    return clean


@dataclass(frozen=True, slots=True)
class TextLayer:
    id: str
    role: str
    name: str
    content: str
    box: tuple[float, float, float, float]
    font_family: str = "noto-sans-sc"
    font_weight: int = 600
    font_style: str = "normal"
    underline: bool = False
    strikethrough: bool = False
    font_size: int = 96
    color: str = "#181F1C"
    text_align: str = "left"
    vertical_align: str = "top"
    line_height: float = 1.2
    letter_spacing: float = 0
    rotation: float = 0
    opacity: float = 1
    stroke_width: int = 0
    stroke_color: str = "#FFFFFF"
    shadow: bool = False
    shadow_color: str = "#000000"
    shadow_blur: int = 0
    shadow_offset_x: int = 0
    shadow_offset_y: int = 0
    background_color: str = ""
    background_opacity: float = 0
    padding: int = 0
    visible: bool = True
    locked: bool = False
    z_index: int = 0
    source: str = "manual"
    copy_block_id: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise DomainValidationError("文字图层必须包含 ID 和名称")
        if self.role not in TEXT_ROLES:
            raise DomainValidationError(f"未知文字角色: {self.role}")
        if len(self.content) > 500:
            raise DomainValidationError("单个文字图层不能超过 500 个字符")
        if not re.fullmatch(r"[a-z0-9_-]{2,80}", self.font_family):
            raise DomainValidationError("字体 ID 格式无效")
        if not 100 <= self.font_weight <= 900 or self.font_weight % 100:
            raise DomainValidationError("字体粗细必须为 100-900 的整百数")
        if self.font_style not in FONT_STYLES:
            raise DomainValidationError("字体样式必须为 normal 或 italic")
        if not 8 <= self.font_size <= 1024:
            raise DomainValidationError("字号必须在 8-1024px 之间")
        if self.text_align not in TEXT_ALIGNMENTS or self.vertical_align not in VERTICAL_ALIGNMENTS:
            raise DomainValidationError("文字对齐方式无效")
        if not .6 <= self.line_height <= 3 or not -20 <= self.letter_spacing <= 100:
            raise DomainValidationError("行高或字间距超出支持范围")
        if not -180 <= self.rotation <= 180 or not 0 <= self.opacity <= 1:
            raise DomainValidationError("旋转或透明度超出支持范围")
        if not 0 <= self.stroke_width <= 32 or not 0 <= self.shadow_blur <= 64:
            raise DomainValidationError("描边或阴影参数超出支持范围")
        if not 0 <= self.background_opacity <= 1 or not 0 <= self.padding <= 256:
            raise DomainValidationError("文字背景或内边距参数超出支持范围")
        if self.background_color:
            _color(self.background_color, "#FFFFFF")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TextLayer:
        return cls(
            id=str(value.get("id", "")), role=str(value.get("role") or "custom"),
            name=str(value.get("name") or "自定义文字"), content=str(value.get("content") or ""),
            box=_box(value.get("box")), font_family=str(value.get("font_family") or "noto-sans-sc"),
            font_weight=int(value.get("font_weight") or 400), font_size=int(value.get("font_size") or 64),
            font_style=str(value.get("font_style") or "normal"), underline=bool(value.get("underline", False)),
            strikethrough=bool(value.get("strikethrough", False)),
            color=_color(value.get("color"), "#181F1C"), text_align=str(value.get("text_align") or "left"),
            vertical_align=str(value.get("vertical_align") or "top"), line_height=float(value.get("line_height") or 1.2),
            letter_spacing=float(value.get("letter_spacing") or 0), rotation=float(value.get("rotation") or 0),
            opacity=float(value.get("opacity") if value.get("opacity") is not None else 1),
            stroke_width=int(value.get("stroke_width") or 0), stroke_color=_color(value.get("stroke_color"), "#FFFFFF"),
            shadow=bool(value.get("shadow", False)), shadow_color=_color(value.get("shadow_color"), "#000000"),
            shadow_blur=int(value.get("shadow_blur") or 0), shadow_offset_x=int(value.get("shadow_offset_x") or 0),
            shadow_offset_y=int(value.get("shadow_offset_y") or 0), background_color=str(value.get("background_color") or ""),
            background_opacity=float(value.get("background_opacity") or 0), padding=int(value.get("padding") or 0),
            visible=bool(value.get("visible", True)), locked=bool(value.get("locked", False)),
            z_index=int(value.get("z_index") or 0), source=str(value.get("source") or "manual"),
            copy_block_id=str(value.get("copy_block_id") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {field: (list(value) if field == "box" else value) for field, value in (
            (name, getattr(self, name)) for name in self.__dataclass_fields__
        )}


@dataclass(frozen=True, slots=True)
class TextDocument:
    candidate_id: str
    version: int
    layers: tuple[TextLayer, ...]
    status: str = "draft"
    source: str = "manual"
    ai_reasoning: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or self.version < 1:
            raise DomainValidationError("文字文档缺少候选或版本")
        if len(self.layers) > 40:
            raise DomainValidationError("单张图片最多支持 40 个文字图层")
        ids = [layer.id for layer in self.layers]
        if len(ids) != len(set(ids)):
            raise DomainValidationError("文字图层 ID 不能重复")
        if self.status not in {"draft", "applied"}:
            raise DomainValidationError("文字文档状态无效")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "version": self.version,
            "layers": [layer.to_dict() for layer in self.layers], "status": self.status,
            "source": self.source, "ai_reasoning": self.ai_reasoning,
            "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TextDocument:
        created_at = value.get("created_at")
        updated_at = value.get("updated_at")
        return cls(
            candidate_id=str(value.get("candidate_id") or ""),
            version=int(value.get("version") or 1),
            layers=tuple(TextLayer.from_dict(layer) for layer in value.get("layers") or []),
            status=str(value.get("status") or "draft"),
            source=str(value.get("source") or "manual"),
            ai_reasoning=str(value.get("ai_reasoning") or ""),
            created_at=datetime.fromisoformat(str(created_at)) if created_at else utc_now(),
            updated_at=datetime.fromisoformat(str(updated_at)) if updated_at else utc_now(),
        )
