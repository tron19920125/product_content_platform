from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from product_content_platform.application import PlatformApplication
from product_content_platform.domain import (
    AssetUsage,
    Candidate,
    CandidateStatus,
    GenerationJob,
    JobStatus,
    PageItem,
    PagePlan,
    PageStatus,
    PageType,
    ProductProfile,
    Project,
    ProjectStatus,
    QAResult,
    QAStatus,
    ReviewDecision,
    ReviewDecisionType,
)

from .local_asset_store import LocalAssetStore
from .sqlite_production_repository import SQLiteProductionRepository
from .sqlite_repository import SQLitePlatformRepository


SHOWCASES = (
    {
        "slug": "square-2048",
        "project_id": "showcase-square-2048",
        "name": "[示例] 2048 方形 · 静谧洗护",
        "sku": "DEMO-SQUARE-2048",
        "library_id": "library-square-2048",
        "template_id": "scene-overlay",
        "page_type": PageType.SCENE,
        "title": "静谧洗护，自成风景",
        "body": "自然光、温润木饰面与石材地面，共同构成真实而高级的家庭洗护空间。",
        "visual_goal": "方形电商主视觉：左上信息留白，商品在右下生活空间中完整呈现。",
        "size": "2048x2048",
    },
    {
        "slug": "landscape-3840",
        "project_id": "showcase-landscape-3840",
        "name": "[示例] 4K 横版 · 宽银幕空间叙事",
        "sku": "DEMO-LANDSCAPE-4K",
        "library_id": "library-landscape-3840",
        "template_id": "landscape-story-left-v1",
        "page_type": PageType.HERO,
        "title": "横向延展，静谧洗护",
        "body": "晨光、石材与木饰面，共同构成宽银幕生活叙事。",
        "visual_goal": "16:9 宽银幕广告：左侧低细节信息区，商品在右侧建筑空间中形成视觉重心。",
        "size": "3840x2160",
    },
    {
        "slug": "portrait-3840",
        "project_id": "showcase-portrait-3840",
        "name": "[示例] 4K 竖版 · 移动端天光海报",
        "sku": "DEMO-PORTRAIT-4K",
        "library_id": "library-portrait-3840",
        "template_id": "portrait-story-top-v1",
        "page_type": PageType.HERO,
        "title": "向上生长的洗护空间",
        "body": "天光倾落，让专业护理成为家的安静一景。",
        "visual_goal": "9:16 移动端海报：上方保留天光文字区，商品在纵向建筑空间下部完整接地。",
        "size": "2160x3840",
    },
)


def seed_showcase_projects(
    *,
    source_root: Path,
    production_root: Path,
    repository: SQLitePlatformRepository,
    platform: PlatformApplication,
    production_repository: SQLiteProductionRepository,
    asset_store: LocalAssetStore,
) -> None:
    """Install immutable showcase results without shipping a machine-specific SQLite database."""
    if not source_root.is_dir():
        return
    product_reference = source_root / "product-reference.jpg"
    for index, row in enumerate(SHOWCASES, start=1):
        slug = str(row["slug"])
        project_id = str(row["project_id"])
        page_id = f"{project_id}-page-1"
        plan_id = f"{project_id}-plan"
        job_id = f"{project_id}-job-1"
        candidate_id = f"{project_id}-candidate-1"
        created_at = datetime(2026, 1, index, 8, 0, tzinfo=timezone.utc)
        project = repository.get_project(project_id)
        if project is None:
            project = Project(
                id=project_id,
                name=str(row["name"]),
                status=ProjectStatus.COMPLETED,
                profile=ProductProfile(
                    sku=str(row["sku"]),
                    name="高端滚筒洗衣机",
                    category="洗衣机",
                    model="DEMO-WM-01",
                    selling_points=("精致衣物护理", "安静融入高端家居", "真实材质与自然光"),
                    parameters={"容量": "10kg", "类型": "滚筒洗衣机"},
                    brand_requirements="克制、温暖、真实材质与自然光",
                    output_requirements=f"内置审计示例：{row['size']}、High、文字独立排版",
                ),
                created_at=created_at,
                updated_at=created_at,
            )
            repository.save_project(project)
        if product_reference.is_file() and not platform.list_assets(project_id):
            relative_path = asset_store.save(product_reference.name, product_reference.read_bytes())
            platform.register_asset(
                project_id,
                AssetUsage.PRODUCT,
                product_reference.name,
                "image/jpeg",
                relative_path,
                product_reference.stat().st_size,
                source="bundled_showcase",
                authorization_status="authorized",
            )
            project = repository.get_project(project_id) or project

        if repository.get_plan(project_id) is None:
            page = PageItem(
                id=page_id,
                order=1,
                page_type=row["page_type"],
                title=str(row["title"]),
                body=str(row["body"]),
                visual_goal=str(row["visual_goal"]),
                template_id=str(row["template_id"]),
                heading_level=1,
                status=PageStatus.READY,
            )
            plan = PagePlan(
                id=plan_id,
                project_id=project_id,
                version=1,
                items=(page,),
                layout_library_id=str(row["library_id"]),
                confirmed=True,
                created_at=created_at,
                updated_at=created_at,
            )
            repository.save_plan(
                plan,
                replace(project, status=ProjectStatus.COMPLETED, updated_at=created_at),
            )

        existing_job = production_repository.get_job(job_id)
        if existing_job is not None:
            if existing_job.trace.get("bundled_showcase") and existing_job.trace.get("reference_count") != 1:
                production_repository.update_job(
                    replace(
                        existing_job,
                        trace={
                            **existing_job.trace,
                            "reference_count": 1,
                            "reference_files": [product_reference.name],
                        },
                    )
                )
            continue
        source_paths = {
            "base": source_root / f"{slug}-base.png",
            "text": source_root / f"{slug}-text.png",
            "composed": source_root / f"{slug}.png",
        }
        if not all(path.is_file() for path in source_paths.values()):
            continue
        relative_root = Path("showcases") / slug
        destination_root = production_root / relative_root
        destination_root.mkdir(parents=True, exist_ok=True)
        for kind, source in source_paths.items():
            shutil.copy2(source, destination_root / f"{kind}.png")

        trace = {
            "stage": "completed",
            "progress": 100,
            "label": "内置示例结果已就绪",
            "plan_version": 1,
            "quality": "high",
            "prompt_version_id": "prompt-lifestyle-scene-v3",
            "bundled_showcase": True,
            "reference_count": 1,
            "reference_files": [product_reference.name],
        }
        job = GenerationJob(
            id=job_id,
            project_id=project_id,
            page_id=page_id,
            recipe_id="commerce-lifestyle-demo-v1",
            status=JobStatus.COMPLETED,
            attempt=1,
            trace=trace,
            created_at=created_at,
            updated_at=created_at,
        )
        production_repository.create_jobs([job])
        candidate = Candidate(
            id=candidate_id,
            job_id=job_id,
            project_id=project_id,
            page_id=page_id,
            candidate_index=1,
            base_path=str(relative_root / "base.png"),
            text_layer_path=str(relative_root / "text.png"),
            composed_path=str(relative_root / "composed.png"),
            prompt="内置审计示例：参考商品重绘进真实空间；指定区域留白；营销文字由独立文字层排版。",
            score=98,
            rank=1,
            status=CandidateStatus.GENERATED,
            metadata={
                "generator": {
                    "provider": "bundled-showcase",
                    "quality": "high",
                    "size": row["size"],
                    "reference_strategy": "model_edit",
                    "reference_count": 1,
                    "layout": {
                        "template_id": row["template_id"],
                        "library_id": row["library_id"],
                        "canvas_size": row["size"],
                    },
                },
                "compose": {"showcase_seed": True, "font_family": "system_sans"},
                "qa": {"policy": "commerce-basic-v1", "showcase_seed": True},
            },
            created_at=created_at,
        )
        qa = QAResult(
            id=f"{candidate_id}-qa",
            candidate_id=candidate_id,
            status=QAStatus.PASS,
            score=98,
            issues=(),
            evidence={
                "showcase_seed": True,
                "canvas_size": row["size"],
                "layout_library_id": row["library_id"],
                "template_id": row["template_id"],
                "text_layer_source": "deterministic_composition",
            },
            created_at=created_at,
        )
        production_repository.save_job_results(job, [candidate], [qa])
        production_repository.save_decision(
            ReviewDecision(
                id=f"{candidate_id}-approval",
                project_id=project_id,
                page_id=page_id,
                candidate_id=candidate_id,
                decision=ReviewDecisionType.APPROVED,
                override_reason="仓库内置验收示例",
                reviewer="showcase-seeder",
                created_at=created_at,
            )
        )
