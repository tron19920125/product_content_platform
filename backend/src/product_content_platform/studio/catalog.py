from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Tool(StrEnum):
    ECOM_SUITE = "ecom_suite"
    A_PLUS = "a_plus_detail"
    MARKETING = "marketing_main_image"
    SCENE = "scene_image"
    SELLING = "selling_point_image"


Ratio = Literal["1:1", "3:4", "4:3", "2:3", "3:2", "16:9", "9:16"]
Resolution = Literal["1k", "2k"]
AssetUsage = Literal["product", "style", "logo"]

# These are application presets, not a claim about a configured model deployment.
IMAGE_SIZES: dict[str, dict[str, tuple[int, int]]] = {
    "1:1": {"1k": (1024, 1024), "2k": (2048, 2048)},
    "3:4": {"1k": (864, 1152), "2k": (1536, 2048)},
    "4:3": {"1k": (1152, 864), "2k": (2048, 1536)},
    "2:3": {"1k": (768, 1152), "2k": (1344, 2016)},
    "3:2": {"1k": (1152, 768), "2k": (2016, 1344)},
    "16:9": {"1k": (1280, 720), "2k": (2048, 1152)},
    "9:16": {"1k": (720, 1280), "2k": (1152, 2048)},
}

SUITE_PURPOSES = {
    "white_background": "白底图", "marketing": "营销主图", "scene": "场景图",
    "selling_point": "卖点图", "detail": "细节图", "dimensions": "尺寸图",
    "features": "功能说明", "instructions": "使用步骤", "comparison": "对比图",
    "package_contents": "包装清单",
}
A_PLUS_PURPOSES = {
    "hero": "首屏", "brand_story": "品牌介绍", "selling_point": "核心卖点",
    "features": "多特性", "scene": "场景", "detail": "细节",
    "comparison": "规格对比", "instructions": "使用说明",
}
TOOL_LABELS = {
    Tool.ECOM_SUITE: "电商套图", Tool.A_PLUS: "A+ 详情图",
    Tool.MARKETING: "营销主图", Tool.SCENE: "场景图", Tool.SELLING: "卖点图",
}
SINGLE_PURPOSES = {
    Tool.MARKETING: "marketing", Tool.SCENE: "scene", Tool.SELLING: "selling_point",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OutputSettings(StrictModel):
    ratio: Ratio = "1:1"
    resolution: Resolution = "2k"

    @property
    def pixels(self) -> tuple[int, int]:
        return IMAGE_SIZES[self.ratio][self.resolution]


class ProductFact(StrictModel):
    # Incomplete user input is autosaved as a draft, never passed to generation.
    name: str = Field(default="", max_length=100)
    value: str = Field(default="", max_length=2000)
    source: str = Field(default="", max_length=2000)

    def validate_for_generation(self) -> None:
        values = (self.name, self.value, self.source)
        if any(not value.strip() or value.strip().casefold() in {"待填写", "待确认", "tbd"} for value in values):
            raise ValueError("商品事实尚未填写完整，请补充名称、实际值及来源，或删除空白条目")


class StudioLayer(StrictModel):
    """Portable editor layer contract shared by saved drafts and work snapshots."""

    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    type: Literal["text", "image"] = "text"
    text: str = Field(default="", max_length=20_000)
    image_url: str | None = Field(default=None, max_length=500)
    asset_id: str | None = Field(default=None, max_length=64)
    x: float = Field(default=0, ge=-100_000, le=100_000)
    y: float = Field(default=0, ge=-100_000, le=100_000)
    width: float = Field(default=320, gt=0, le=100_000)
    height: float = Field(default=120, gt=0, le=100_000)
    rotation: float = Field(default=0, ge=-360, le=360)
    font: Literal["StudioSans", "StudioSerif", "StudioWenkai"] = "StudioSans"
    fontSize: float = Field(default=48, ge=8, le=2048)
    color: str = Field(default="#182230", pattern=r"^#[0-9a-fA-F]{6}$")
    bold: bool = False
    italic: bool = False
    align: Literal["left", "center", "right"] = "left"
    lineHeight: float = Field(default=1.3, ge=0.5, le=5)
    letterSpacing: float = Field(default=0, ge=-100, le=500)
    stroke: float = Field(default=0, ge=0, le=100)
    strokeColor: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    shadow: float = Field(default=0, ge=0, le=200)
    opacity: float = Field(default=1, ge=0, le=1)
    locked: bool = False
    hidden: bool = False

    @model_validator(mode="after")
    def validate_source(self) -> StudioLayer:
        if self.type == "image":
            if not self.asset_id or self.image_url != f"/api/studio/assets/{self.asset_id}/source":
                raise ValueError("图片图层必须引用已上传的素材及其原图地址")
        elif self.asset_id or self.image_url:
            raise ValueError("文字图层不能携带图片素材")
        return self


class PageDraft(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    purpose: str = Field(min_length=1, max_length=40)
    title: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=8000)
    visual_goal: str = Field(default="", max_length=8000)
    output: OutputSettings | None = None
    skipped: bool = False


class DraftContent(StrictModel):
    tool: Tool = Field(strict=False)
    product_asset_ids: list[str] = Field(default_factory=list, max_length=6)
    style_asset_ids: list[str] = Field(default_factory=list, max_length=2)
    logo_asset_id: str | None = None
    product_name: str = Field(default="", max_length=200)
    sku: str = Field(default="", max_length=200)
    category: str = Field(default="", max_length=200)
    requirements: str = Field(default="", max_length=16000)
    facts: list[ProductFact] = Field(default_factory=list, max_length=100)
    market: Literal["domestic_zh", "amazon_en"] = "domestic_zh"
    style: Literal["auto", "minimal", "home", "technology", "premium", "promotion"] = "auto"
    brand_color: str = Field(default="", pattern=r"^$|^#[0-9a-fA-F]{6}$")
    brand_font: Literal["auto", "sans", "serif", "wenkai"] = "auto"
    text_mode: Literal["native", "background_only"] = "native"
    output: OutputSettings = Field(default_factory=OutputSettings)
    candidate_count: Literal[1, 2, 4] = 1
    pages: list[PageDraft] = Field(default_factory=list, max_length=15)

    @field_validator("candidate_count", mode="before")
    @classmethod
    def integer_candidate_count(cls, value):
        if type(value) is not int:
            raise ValueError("候选数必须是整数 1、2 或 4")
        return value

    @model_validator(mode="after")
    def validate_structure(self) -> DraftContent:
        # Empty/incomplete drafts are valid. Submission requirements are separate.
        purposes = purposes_for(self.tool)
        if len(self.pages) > page_limit(self.tool):
            raise ValueError(f"{TOOL_LABELS[self.tool]}最多 {page_limit(self.tool)} 页")
        if any(page.purpose not in purposes for page in self.pages):
            raise ValueError("页面用途不属于当前工具")
        if len({page.id for page in self.pages}) != len(self.pages):
            raise ValueError("页面标识不能重复；重排应保留原标识")
        references = self.product_asset_ids + self.style_asset_ids
        if self.logo_asset_id:
            references.append(self.logo_asset_id)
        if any(not value.strip() or len(value) > 64 for value in references):
            raise ValueError("素材标识无效")
        if len(set(references)) != len(references):
            raise ValueError("素材不能重复使用或同时作为商品与风格依据")
        return self


def page_limit(tool: Tool) -> int:
    return 15 if tool == Tool.ECOM_SUITE else 6 if tool == Tool.A_PLUS else 1


def purposes_for(tool: Tool) -> dict[str, str]:
    if tool == Tool.ECOM_SUITE:
        return SUITE_PURPOSES
    if tool == Tool.A_PLUS:
        return A_PLUS_PURPOSES
    purpose = SINGLE_PURPOSES[tool]
    return {purpose: SUITE_PURPOSES[purpose]}


def default_draft(tool: Tool) -> DraftContent:
    purposes = (
        ["marketing", "scene", "selling_point"] if tool == Tool.ECOM_SUITE else
        ["hero", "selling_point", "scene"] if tool == Tool.A_PLUS else
        [SINGLE_PURPOSES[tool]]
    )
    return DraftContent(
        tool=tool,
        market="amazon_en" if tool == Tool.A_PLUS else "domestic_zh",
        text_mode="background_only" if tool == Tool.SCENE else "native",
        output=OutputSettings(ratio="16:9" if tool == Tool.A_PLUS else "3:4" if tool == Tool.SCENE else "1:1"),
        pages=[PageDraft(purpose=purpose) for purpose in purposes],
    )


def catalog(*, reference_limit: int, max_upload_bytes: int) -> dict:
    return {
        "schema_version": 1,
        "tools": [
            {
                "id": tool.value, "label": TOOL_LABELS[tool],
                "max_pages": page_limit(tool), "requires_plan": tool == Tool.A_PLUS,
                "purposes": [{"id": key, "label": value} for key, value in purposes_for(tool).items()],
                "defaults": default_draft(tool).model_dump(mode="json"),
            }
            for tool in Tool
        ],
        "sizes": [
            {"ratio": ratio, "resolution": level, "width": size[0], "height": size[1]}
            for ratio, levels in IMAGE_SIZES.items() for level, size in levels.items()
        ],
        "quality": "high", "candidate_counts": [1, 2, 4],
        "limits": {
            "product_references": 6, "style_references": 2,
            "total_references": reference_limit, "ai_edit_reserved_references": 1,
            "upload_bytes": max_upload_bytes,
        },
        "generation_available": False,
        "generation_submission_available": True,
        "demo_available": True,
        "deployment_validation": "pending",
        "note": "可提交智能生成任务并回放预置案例；尚无常驻图片执行器。尺寸是应用预设，后续常驻模型接入时需逐档验收。",
    }
