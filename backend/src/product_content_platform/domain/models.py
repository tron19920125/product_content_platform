from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .errors import DomainValidationError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    PLANNED = "planned"
    PRODUCING = "producing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class BatchStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    PAUSED = "paused"


class BatchItemStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"


class AssetUsage(StrEnum):
    PRODUCT = "product"
    DETAIL = "detail"
    BRAND = "brand"
    SCENE = "scene"


class PageType(StrEnum):
    HERO = "hero"
    SELLING_POINT = "selling_point"
    FUNCTION = "function"
    SCENE = "scene"
    PARAMETERS = "parameters"


class PageStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"


class PlanningRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DISMISSED = "dismissed"


@dataclass(frozen=True, slots=True)
class ProductProfile:
    sku: str
    name: str
    category: str
    model: str = ""
    selling_points: tuple[str, ...] = ()
    parameters: dict[str, str] = field(default_factory=dict)
    reference_assets: tuple[str, ...] = ()
    brand_requirements: str = ""
    output_requirements: str = ""

    def __post_init__(self) -> None:
        required = {"sku": self.sku, "name": self.name, "category": self.category}
        missing = [key for key, value in required.items() if not value.strip()]
        if missing:
            raise DomainValidationError(f"商品档案缺少必填字段: {', '.join(missing)}")

        normalized_parameters = {str(key).strip(): str(value).strip() for key, value in self.parameters.items()}
        object.__setattr__(self, "sku", self.sku.strip())
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "category", self.category.strip())
        object.__setattr__(self, "model", self.model.strip())
        object.__setattr__(self, "selling_points", tuple(point.strip() for point in self.selling_points if point.strip()))
        object.__setattr__(self, "parameters", normalized_parameters)
        object.__setattr__(self, "reference_assets", tuple(asset for asset in self.reference_assets if asset))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "model": self.model,
            "selling_points": list(self.selling_points),
            "parameters": dict(self.parameters),
            "reference_assets": list(self.reference_assets),
            "brand_requirements": self.brand_requirements,
            "output_requirements": self.output_requirements,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ProductProfile:
        return cls(
            sku=str(value.get("sku", "")),
            name=str(value.get("name", "")),
            category=str(value.get("category", "")),
            model=str(value.get("model", "")),
            selling_points=tuple(value.get("selling_points") or ()),
            parameters=dict(value.get("parameters") or {}),
            reference_assets=tuple(value.get("reference_assets") or ()),
            brand_requirements=str(value.get("brand_requirements", "")),
            output_requirements=str(value.get("output_requirements", "")),
        )


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    profile: ProductProfile
    status: ProjectStatus = ProjectStatus.DRAFT
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class Asset:
    id: str
    project_id: str
    usage: AssetUsage
    file_name: str
    mime_type: str
    storage_path: str
    size_bytes: int
    source: str = "user_upload"
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class FeaturePoint:
    id: str
    title: str
    description: str = ""
    icon_concept: str = ""
    fact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.title.strip():
            raise DomainValidationError("图文卖点必须包含 ID 和标题")
        if len(self.title) > 40 or len(self.description) > 120 or len(self.icon_concept) > 120:
            raise DomainValidationError("图文卖点文案或图标概念过长")
        object.__setattr__(self, "id", self.id.strip())
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "icon_concept", self.icon_concept.strip())
        object.__setattr__(self, "fact_refs", tuple(dict.fromkeys(value.strip() for value in self.fact_refs if value.strip())))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "icon_concept": self.icon_concept,
            "fact_refs": list(self.fact_refs),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> FeaturePoint:
        return cls(
            id=str(value.get("id") or ""),
            title=str(value.get("title") or ""),
            description=str(value.get("description") or ""),
            icon_concept=str(value.get("icon_concept") or ""),
            fact_refs=tuple(str(item) for item in value.get("fact_refs") or ()),
        )


@dataclass(frozen=True, slots=True)
class PageItem:
    id: str
    order: int
    page_type: PageType
    title: str
    body: str
    visual_goal: str
    template_id: str
    feature_points: tuple[FeaturePoint, ...] = ()
    heading_level: int = 1
    status: PageStatus = PageStatus.DRAFT

    def __post_init__(self) -> None:
        if not 1 <= self.heading_level <= 5:
            raise DomainValidationError("标题层级必须为 1 至 5")
        if len(self.feature_points) > 6:
            raise DomainValidationError("单页最多支持 6 个图文卖点")
        point_ids = [point.id for point in self.feature_points]
        if len(point_ids) != len(set(point_ids)):
            raise DomainValidationError("图文卖点 ID 不能重复")


@dataclass(frozen=True, slots=True)
class PagePlan:
    id: str
    project_id: str
    version: int
    items: tuple[PageItem, ...]
    layout_library_id: str = "library-square-2048"
    confirmed: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.items:
            raise DomainValidationError("页面规划至少需要一个页面")
        orders = [item.order for item in self.items]
        if len(orders) != len(set(orders)):
            raise DomainValidationError("页面规划中的顺序不能重复")


@dataclass(frozen=True, slots=True)
class PlanningRun:
    id: str
    project_id: str
    status: PlanningRunStatus
    layout_library_id: str
    base_plan_version: int = 0
    input_snapshot: dict[str, Any] = field(default_factory=dict)
    suggestion: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    degraded: bool = False
    applied_fields: dict[str, list[str]] = field(default_factory=dict)
    applied_plan_version: int = 0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class BatchItem:
    id: str
    batch_id: str
    project_id: str
    sku: str
    status: BatchItemStatus = BatchItemStatus.PENDING
    override_config: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True, slots=True)
class Batch:
    id: str
    name: str
    status: BatchStatus
    common_config: dict[str, Any]
    items: tuple[BatchItem, ...]
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def progress(self) -> dict[str, int]:
        counts = {status.value: 0 for status in BatchItemStatus}
        for item in self.items:
            counts[item.status.value] += 1
        counts["total"] = len(self.items)
        return counts
