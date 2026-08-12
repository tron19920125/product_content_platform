from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from product_content_platform.domain import (
    Asset,
    AssetUsage,
    Batch,
    BatchItem,
    BatchItemStatus,
    BatchStatus,
    DomainValidationError,
    EntityNotFoundError,
    PageItem,
    PagePlan,
    PageStatus,
    PageType,
    ProductProfile,
    Project,
    ProjectStatus,
)

from .ports import PlatformRepository


@dataclass(frozen=True, slots=True)
class ProjectInput:
    project_name: str
    profile: ProductProfile


@dataclass(frozen=True, slots=True)
class BatchSkuInput:
    profile: ProductProfile
    override_config: dict[str, Any] = field(default_factory=dict)


class PlatformApplication:
    """Use-case module for projects and multi-SKU batches."""

    def __init__(self, repository: PlatformRepository) -> None:
        self._repository = repository

    def create_project(self, request: ProjectInput) -> Project:
        name = request.project_name.strip()
        if not name:
            raise DomainValidationError("项目名称不能为空")

        project = Project(id=str(uuid4()), name=name, profile=request.profile)
        self._repository.save_project(project)
        return project

    def create_laundry_demo_project(self) -> tuple[Project, PagePlan]:
        """Create the reproducible one-page golden demo without bundling user assets."""
        demo_id = str(uuid4())
        profile = ProductProfile(
            sku=f"DEMO-LIFE-{demo_id[:8].upper()}",
            name="高端滚筒洗衣机",
            category="洗衣机",
            model="DEMO-WM-01",
            selling_points=("精致衣物护理", "安静融入高端家居", "真实材质与自然光"),
            parameters={"容量": "10kg", "类型": "滚筒洗衣机"},
            output_requirements="黄金演示：2048x2048、High、高端生活场景演示配方",
        )
        project = Project(id=demo_id, name="2048 高端洗护黄金演示", profile=profile)
        self._repository.save_project(project)
        plan = PagePlan(
            id=str(uuid4()),
            project_id=project.id,
            version=1,
            confirmed=True,
            items=(
                PageItem(
                    id=str(uuid4()),
                    order=1,
                    page_type=PageType.SCENE,
                    title="静谧洗护，自成风景",
                    body="自然光、温润木饰面与石材地面，共同构成真实而高级的家庭洗护空间。",
                    visual_goal=(
                        "完整高端住宅洗衣房场景，晨间自然光从左侧窗户进入，温润木饰面墙、"
                        "浅灰石材地面、亚麻收纳篮、绿植和叠放毛巾形成前后景层次；"
                        "商品完整位于右下，左上保持安静低细节留白。"
                    ),
                    template_id="scene-overlay",
                    heading_level=2,
                    status=PageStatus.READY,
                ),
            ),
        )
        planned_project = replace(
            project,
            status=ProjectStatus.PLANNED,
            updated_at=datetime.now(timezone.utc),
        )
        self._repository.save_plan(plan, planned_project)
        return planned_project, plan

    def get_project(self, project_id: str) -> Project:
        project = self._repository.get_project(project_id)
        if project is None:
            raise EntityNotFoundError(f"项目不存在: {project_id}")
        return project

    def list_projects(self) -> list[Project]:
        return self._repository.list_projects()

    def set_project_status(self, project_id: str, status: ProjectStatus) -> Project:
        project = self.get_project(project_id)
        updated = replace(project, status=status, updated_at=datetime.now(timezone.utc))
        self._repository.update_project(updated)
        return updated

    def update_project(self, project_id: str, profile: ProductProfile, project_name: str = "") -> Project:
        project = self.get_project(project_id)
        updated = replace(
            project,
            name=project_name.strip() or project.name,
            profile=profile,
            updated_at=datetime.now(timezone.utc),
        )
        self._repository.update_project(updated)
        return updated

    def clone_project(self, project_id: str) -> Project:
        source = self.get_project(project_id)
        cloned = Project(
            id=str(uuid4()),
            name=f"{source.name} - 副本",
            profile=replace(source.profile, reference_assets=()),
        )
        self._repository.save_project(cloned)
        for asset in self._repository.list_assets(project_id):
            self.register_asset(
                cloned.id,
                asset.usage,
                asset.file_name,
                asset.mime_type,
                asset.storage_path,
                asset.size_bytes,
                asset.source,
            )
        source_plan = self._repository.get_plan(project_id)
        if source_plan is not None:
            cloned = self.get_project(cloned.id)
            plan = PagePlan(
                id=str(uuid4()),
                project_id=cloned.id,
                version=1,
                items=tuple(
                    replace(item, id=str(uuid4()), status=PageStatus.DRAFT)
                    for item in source_plan.items
                ),
                layout_library_id=source_plan.layout_library_id,
                confirmed=False,
            )
            self._repository.save_plan(plan, cloned)
        return self.get_project(cloned.id)

    def register_asset(
        self,
        project_id: str,
        usage: AssetUsage,
        file_name: str,
        mime_type: str,
        storage_path: str,
        size_bytes: int,
        source: str = "user_upload",
    ) -> Asset:
        project = self.get_project(project_id)
        asset = Asset(
            id=str(uuid4()),
            project_id=project_id,
            usage=usage,
            file_name=file_name.strip(),
            mime_type=mime_type.strip() or "application/octet-stream",
            storage_path=storage_path,
            size_bytes=size_bytes,
            source=source.strip() or "user_upload",
        )
        profile = replace(
            project.profile,
            reference_assets=(*project.profile.reference_assets, asset.id),
        )
        updated_project = replace(project, profile=profile, updated_at=datetime.now(timezone.utc))
        self._repository.save_asset(asset, updated_project)
        return asset

    def get_asset(self, asset_id: str) -> Asset:
        asset = self._repository.get_asset(asset_id)
        if asset is None:
            raise EntityNotFoundError(f"素材不存在: {asset_id}")
        return asset

    def list_assets(self, project_id: str) -> list[Asset]:
        self.get_project(project_id)
        return self._repository.list_assets(project_id)

    def generate_plan(
        self,
        project_id: str,
        layout_library_id: str = "library-square-2048",
        template_ids: dict[PageType, str] | None = None,
    ) -> PagePlan:
        project = self.get_project(project_id)
        profile = project.profile
        points = list(profile.selling_points)
        first_point = points[0] if points else "专业呵护每一次使用"
        second_point = points[1] if len(points) > 1 else "智能科技带来省心体验"
        parameters = " · ".join(f"{key} {value}" for key, value in list(profile.parameters.items())[:4])
        if not parameters:
            parameters = f"型号 {profile.model or profile.sku}"
        default_template_ids = {
            PageType.HERO: "hero-center",
            PageType.SELLING_POINT: "split-left",
            PageType.FUNCTION: "split-right",
            PageType.SCENE: "scene-overlay",
            PageType.PARAMETERS: "data-grid",
        }
        selected_template_ids = {**default_template_ids, **(template_ids or {})}
        page_specs = [
            (PageType.HERO, profile.name, first_point, "清晰呈现商品全貌与品牌气质", selected_template_ids[PageType.HERO], 1),
            (PageType.SELLING_POINT, first_point, f"围绕{first_point}说明核心价值", "突出一个核心部件或使用效果", selected_template_ids[PageType.SELLING_POINT], 2),
            (PageType.FUNCTION, second_point, f"围绕{second_point}说明功能体验", "通过细节或功能场景解释卖点", selected_template_ids[PageType.FUNCTION], 2),
            (PageType.SCENE, "融入理想生活", f"让{profile.name}自然融入目标用户的生活空间", "完整生活场景，商品主体清晰可见", selected_template_ids[PageType.SCENE], 2),
            (PageType.PARAMETERS, "关键参数", parameters, "结构化展示已确认的商品事实", selected_template_ids[PageType.PARAMETERS], 2),
        ]
        existing = self._repository.get_plan(project_id)
        plan = PagePlan(
            id=existing.id if existing else str(uuid4()),
            project_id=project_id,
            version=(existing.version + 1) if existing else 1,
            layout_library_id=layout_library_id,
            items=tuple(
                PageItem(
                    id=str(uuid4()),
                    order=index,
                    page_type=page_type,
                    title=title,
                    body=body,
                    visual_goal=visual_goal,
                    template_id=template_id,
                    heading_level=heading_level,
                )
                for index, (page_type, title, body, visual_goal, template_id, heading_level) in enumerate(page_specs, start=1)
            ),
        )
        self._repository.save_plan(
            plan,
            replace(project, status=ProjectStatus.DRAFT, updated_at=datetime.now(timezone.utc)),
        )
        return plan

    def get_plan(self, project_id: str) -> PagePlan:
        self.get_project(project_id)
        plan = self._repository.get_plan(project_id)
        if plan is None:
            raise EntityNotFoundError(f"项目尚未生成页面规划: {project_id}")
        return plan

    def save_plan(
        self,
        project_id: str,
        items: Iterable[PageItem],
        confirmed: bool = False,
        layout_library_id: str = "",
    ) -> PagePlan:
        project = self.get_project(project_id)
        current = self._repository.get_plan(project_id)
        if current is None:
            raise EntityNotFoundError(f"项目尚未生成页面规划: {project_id}")
        normalized = tuple(sorted(items, key=lambda item: item.order))
        plan = PagePlan(
            id=current.id,
            project_id=project_id,
            version=current.version + 1,
            items=tuple(replace(item, status=PageStatus.READY if confirmed else PageStatus.DRAFT) for item in normalized),
            layout_library_id=layout_library_id or current.layout_library_id,
            confirmed=confirmed,
            created_at=current.created_at,
        )
        project_status = ProjectStatus.PLANNED if confirmed else ProjectStatus.DRAFT
        self._repository.save_plan(
            plan,
            replace(project, status=project_status, updated_at=datetime.now(timezone.utc)),
        )
        return plan

    def create_batch(
        self,
        name: str,
        sku_inputs: Iterable[BatchSkuInput],
        common_config: dict[str, Any] | None = None,
    ) -> Batch:
        batch_name = name.strip()
        if not batch_name:
            raise DomainValidationError("批量任务名称不能为空")

        inputs = list(sku_inputs)
        if not inputs:
            raise DomainValidationError("批量任务至少需要一个SKU")

        sku_values = [item.profile.sku for item in inputs]
        duplicate_skus = sorted({sku for sku in sku_values if sku_values.count(sku) > 1})
        if duplicate_skus:
            raise DomainValidationError(f"批量任务包含重复SKU: {', '.join(duplicate_skus)}")

        batch_id = str(uuid4())
        projects: list[Project] = []
        items: list[BatchItem] = []
        for item in inputs:
            project = Project(
                id=str(uuid4()),
                name=f"{batch_name} - {item.profile.sku}",
                profile=item.profile,
            )
            projects.append(project)
            items.append(
                BatchItem(
                    id=str(uuid4()),
                    batch_id=batch_id,
                    project_id=project.id,
                    sku=item.profile.sku,
                    override_config=dict(item.override_config),
                )
            )

        batch = Batch(
            id=batch_id,
            name=batch_name,
            status=BatchStatus.READY,
            common_config=dict(common_config or {}),
            items=tuple(items),
        )
        self._repository.save_batch(batch, projects)
        return batch

    def get_batch(self, batch_id: str) -> Batch:
        batch = self._repository.get_batch(batch_id)
        if batch is None:
            raise EntityNotFoundError(f"批量任务不存在: {batch_id}")
        return batch

    def list_batches(self) -> list[Batch]:
        return self._repository.list_batches()

    def set_batch_item_status(
        self,
        batch_id: str,
        item_id: str,
        status: BatchItemStatus,
        error: str = "",
    ) -> Batch:
        batch = self._repository.update_batch_item(batch_id, item_id, status, error.strip())
        if batch is None:
            raise EntityNotFoundError(f"批量任务或SKU不存在: {batch_id}/{item_id}")
        return batch

    def set_batch_status(self, batch_id: str, status: BatchStatus) -> Batch:
        batch = self._repository.set_batch_status(batch_id, status.value)
        if batch is None:
            raise EntityNotFoundError(f"批量任务不存在: {batch_id}")
        return batch
    PageItem,
    PagePlan,
    PageStatus,
    PageType,
