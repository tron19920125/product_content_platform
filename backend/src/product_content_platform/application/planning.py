from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from product_content_platform.domain import (
    AssetUsage,
    DomainValidationError,
    EntityNotFoundError,
    PageItem,
    PagePlan,
    PageStatus,
    PageType,
    PlanningRun,
    PlanningRunStatus,
    ProjectStatus,
)
from product_content_platform.planning import ContentPlanner

from .platform import PlatformApplication
from .ports import PlatformRepository


class PlanningApplication:
    def __init__(
        self,
        platform: PlatformApplication,
        repository: PlatformRepository,
        planner: ContentPlanner,
        asset_resolver: Callable[[str], Path],
    ) -> None:
        self._platform = platform
        self._repository = repository
        self._planner = planner
        self._asset_resolver = asset_resolver

    def start(self, project_id: str, layout_library_id: str, templates: list[dict[str, Any]]) -> PlanningRun:
        project = self._platform.get_project(project_id)
        current = self._repository.get_plan(project_id)
        specs = self._page_specs(current, templates)
        if not specs:
            raise DomainValidationError("所选版式库中没有可用于内容规划的已发布模板")
        assets = [
            asset for asset in self._platform.list_assets(project_id)
            if asset.mime_type.startswith("image/")
            and asset.usage in {AssetUsage.PRODUCT, AssetUsage.DETAIL}
            and asset.authorization_status != "restricted"
        ]
        input_snapshot = {
            "profile": project.profile.to_dict(),
            "templates": specs,
            "assets": [
                {
                    "id": asset.id, "file_name": asset.file_name, "usage": asset.usage.value,
                    "authorization_status": asset.authorization_status, "storage_path": asset.storage_path,
                }
                for asset in assets
            ],
        }
        run = PlanningRun(
            id=str(uuid4()), project_id=project_id, status=PlanningRunStatus.QUEUED,
            layout_library_id=layout_library_id,
            base_plan_version=current.version if current else 0,
            input_snapshot=input_snapshot,
        )
        self._repository.save_planning_run(run)
        return run

    def process(self, run_id: str) -> PlanningRun:
        run = self.get(run_id)
        if run.status not in {PlanningRunStatus.QUEUED, PlanningRunStatus.RUNNING}:
            return run
        running = replace(run, status=PlanningRunStatus.RUNNING, updated_at=datetime.now(timezone.utc))
        self._repository.save_planning_run(running)
        try:
            project = self._platform.get_project(run.project_id)
            reference_paths = [
                self._asset_resolver(str(item["storage_path"]))
                for item in run.input_snapshot.get("assets", [])
            ]
            suggestion = self._planner.create_suggestion(
                profile=project.profile,
                template_specs=list(run.input_snapshot.get("templates") or []),
                reference_paths=reference_paths,
            )
            completed = replace(
                running,
                status=PlanningRunStatus.COMPLETED,
                suggestion=suggestion,
                degraded=bool(suggestion.get("degraded")),
                error=str(suggestion.get("error") or ""),
                updated_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            completed = replace(
                running, status=PlanningRunStatus.FAILED, error=str(exc),
                updated_at=datetime.now(timezone.utc),
            )
        self._repository.save_planning_run(completed)
        return completed

    def get(self, run_id: str) -> PlanningRun:
        run = self._repository.get_planning_run(run_id)
        if run is None:
            raise EntityNotFoundError(f"内容规划运行不存在: {run_id}")
        return run

    def list(self, project_id: str) -> list[PlanningRun]:
        self._platform.get_project(project_id)
        return self._repository.list_planning_runs(project_id)

    def dismiss(self, project_id: str, run_id: str) -> PlanningRun:
        run = self.get(run_id)
        if run.project_id != project_id:
            raise EntityNotFoundError(f"内容规划运行不存在: {run_id}")
        if run.status not in {PlanningRunStatus.COMPLETED, PlanningRunStatus.FAILED}:
            raise DomainValidationError("正在生成的规划建议不能忽略")
        dismissed = replace(
            run, status=PlanningRunStatus.DISMISSED, updated_at=datetime.now(timezone.utc)
        )
        self._repository.save_planning_run(dismissed)
        return dismissed

    def apply(
        self,
        project_id: str,
        run_id: str,
        selected_fields: dict[str, list[str]] | None = None,
    ) -> PagePlan:
        project = self._platform.get_project(project_id)
        run = self.get(run_id)
        if run.project_id != project_id:
            raise DomainValidationError("规划建议不属于当前项目")
        if run.status is not PlanningRunStatus.COMPLETED:
            raise DomainValidationError("规划建议尚未生成完成")
        suggestion_rows = list(run.suggestion.get("pages") or [])
        if not suggestion_rows:
            raise DomainValidationError("规划建议没有可应用的页面")
        allowed_fields = {"title", "body", "visual_goal"}
        selections = selected_fields or {
            str(row["key"]): sorted(allowed_fields) for row in suggestion_rows
        }
        invalid = {
            field for fields in selections.values() for field in fields if field not in allowed_fields
        }
        if invalid:
            raise DomainValidationError(f"不支持应用这些规划字段: {', '.join(sorted(invalid))}")
        current = self._repository.get_plan(project_id)
        current_by_id = {item.id: item for item in current.items} if current else {}
        items: list[PageItem] = []
        applied: dict[str, list[str]] = {}
        for order, row in enumerate(suggestion_rows, start=1):
            key = str(row["key"])
            previous = current_by_id.get(key)
            fields = sorted(set(selections.get(key) or []))
            if previous:
                values = {
                    name: str(row.get(name) or getattr(previous, name)) if name in fields else getattr(previous, name)
                    for name in allowed_fields
                }
                item = replace(previous, **values, order=order, status=PageStatus.DRAFT)
            else:
                item = PageItem(
                    id=str(uuid4()), order=order, page_type=PageType(str(row["page_type"])),
                    title=str(row.get("title") or "未命名页面") if "title" in fields else "未命名页面",
                    body=str(row.get("body") or "") if "body" in fields else "",
                    visual_goal=str(row.get("visual_goal") or "") if "visual_goal" in fields else "",
                    template_id=str(row["template_id"]),
                    heading_level=1 if row["page_type"] == PageType.HERO.value else 2,
                    status=PageStatus.DRAFT,
                )
            items.append(item)
            if fields:
                applied[key] = fields
        plan = PagePlan(
            id=current.id if current else str(uuid4()), project_id=project_id,
            version=(current.version + 1) if current else 1, items=tuple(items),
            layout_library_id=run.layout_library_id, confirmed=False,
            created_at=current.created_at if current else datetime.now(timezone.utc),
        )
        self._repository.save_plan(
            plan,
            replace(project, status=ProjectStatus.DRAFT, updated_at=datetime.now(timezone.utc)),
        )
        self._repository.save_planning_run(replace(
            run, applied_fields=applied, applied_plan_version=plan.version,
            updated_at=datetime.now(timezone.utc),
        ))
        return plan

    @staticmethod
    def _page_specs(current: PagePlan | None, templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def spec(key: str, page_type: PageType, template: dict[str, Any]) -> dict[str, Any]:
            return {
                "key": key, "page_type": page_type.value, "template_id": template["id"],
                "template_name": template.get("name", ""),
                "scene_prompt_hint": template.get("scene_prompt_hint", ""),
                "composition_instruction": template.get("composition_instruction", ""),
            }

        if current:
            by_id = {item["id"]: item for item in templates}
            result = []
            for page in current.items:
                template = by_id.get(page.template_id)
                if template is None:
                    template = next((item for item in templates if page.page_type.value in item.get("page_types", [])), None)
                if template:
                    result.append(spec(page.id, page.page_type, template))
            return result
        result = []
        for index, page_type in enumerate(PageType, start=1):
            template = next((item for item in templates if page_type.value in item.get("page_types", [])), None)
            if template is None and templates:
                template = templates[0]
            if template:
                result.append(spec(f"page-{index}-{page_type.value}", page_type, template))
        return result
