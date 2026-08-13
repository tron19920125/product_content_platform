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

AZURE_ACCEPTANCE_PROJECT_ID = "2b5deb3c-e86b-4cfa-85b5-7429536e91f0"
AZURE_ACCEPTANCE_MARKER = "仓库内置历史 Azure 五页验收快照"
AZURE_ACCEPTANCE_PAGES = (
    {
        "order": 1,
        "page_id": "1fdd8d27-194f-457d-9b3b-fffbb6edef68",
        "page_type": PageType.HERO,
        "template_id": "hero-center",
        "title": "静谧洗护，自成风景",
        "body": "10kg 大容量，融入现代家居。",
        "visual_goal": "高端现代家居主视觉，左上文案留白，商品在右下完整呈现。",
        "elapsed_seconds": 133.402,
    },
    {
        "order": 2,
        "page_id": "b8163ea0-e86e-4ab0-90d6-2a13d6f0b3d4",
        "page_type": PageType.SELLING_POINT,
        "template_id": "split-left",
        "title": "衣物护理，也是一种质感",
        "body": "柔和光影，呈现精致洗护日常。",
        "visual_goal": "衣帽间生活方式场景，左侧承载文案，商品在右下与空间融合。",
        "elapsed_seconds": 126.305,
    },
    {
        "order": 3,
        "page_id": "a1bec8b9-76d2-40e6-9d9d-b088ecc9ecd2",
        "page_type": PageType.FUNCTION,
        "template_id": "split-right",
        "title": "轻启舱门，呵护从容",
        "body": "真实材质与克制陈设，强调产品细节。",
        "visual_goal": "左侧商品细节、右侧低细节文案区，突出开门结构和材质。",
        "elapsed_seconds": 122.661,
    },
    {
        "order": 4,
        "page_id": "5bcae0c9-c386-4123-8db4-0f95b6cced3a",
        "page_type": PageType.SCENE,
        "template_id": "scene-overlay",
        "title": "让洗护，成为空间的一部分",
        "body": "安静融入客厅与洗衣空间。",
        "visual_goal": "高端洗护生活场景，商品成为建筑空间的一部分。",
        "elapsed_seconds": 130.819,
    },
    {
        "order": 5,
        "page_id": "8be1bdf0-25f4-4ff8-87c6-2a49a06f4d09",
        "page_type": PageType.PARAMETERS,
        "template_id": "data-grid",
        "title": "TG10EK60",
        "body": "10kg 大容量滚筒洗衣机。",
        "visual_goal": "以克制的参数文案和完整商品图完成详情页收束。",
        "elapsed_seconds": 129.131,
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
                "compose": {
                    "showcase_seed": True,
                    "font_family": "system_sans",
                    "title_color": "#1F3027",
                    "body_color": "#42564A",
                    "canvas": [int(part) for part in str(row["size"]).split("x")],
                },
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

    _seed_azure_acceptance_project(
        source_root=source_root.parent / "azure-five-page-acceptance",
        product_reference=product_reference,
        production_root=production_root,
        repository=repository,
        platform=platform,
        production_repository=production_repository,
        asset_store=asset_store,
    )


def _seed_azure_acceptance_project(
    *,
    source_root: Path,
    product_reference: Path,
    production_root: Path,
    repository: SQLitePlatformRepository,
    platform: PlatformApplication,
    production_repository: SQLiteProductionRepository,
    asset_store: LocalAssetStore,
) -> None:
    """Restore the approved five-page Azure acceptance snapshot on clean deployments."""
    if not source_root.is_dir():
        return
    project = repository.get_project(AZURE_ACCEPTANCE_PROJECT_ID)
    if project is not None and project.profile.output_requirements != AZURE_ACCEPTANCE_MARKER:
        # Never overwrite the real local project when it already exists and has continued evolving.
        return

    created_at = datetime(2026, 8, 10, 19, 5, 29, tzinfo=timezone.utc)
    if project is None:
        project = Project(
            id=AZURE_ACCEPTANCE_PROJECT_ID,
            name="Azure 2048 High Five Page Acceptance",
            status=ProjectStatus.COMPLETED,
            profile=ProductProfile(
                sku="DEMO-LIFE-2048",
                name="高端滚筒洗衣机",
                category="洗衣机",
                model="TG10EK60",
                selling_points=("精致衣物护理", "安静融入高端家居", "真实材质与自然光"),
                parameters={"容量": "10kg", "类型": "滚筒洗衣机"},
                brand_requirements="克制、温暖、真实材质与自然光",
                output_requirements=AZURE_ACCEPTANCE_MARKER,
            ),
            created_at=created_at,
            updated_at=created_at,
        )
        repository.save_project(project)

    if product_reference.is_file() and not platform.list_assets(AZURE_ACCEPTANCE_PROJECT_ID):
        relative_path = asset_store.save(product_reference.name, product_reference.read_bytes())
        platform.register_asset(
            AZURE_ACCEPTANCE_PROJECT_ID,
            AssetUsage.PRODUCT,
            product_reference.name,
            "image/jpeg",
            relative_path,
            product_reference.stat().st_size,
            source="bundled_azure_acceptance",
        )
        project = repository.get_project(AZURE_ACCEPTANCE_PROJECT_ID) or project

    if repository.get_plan(AZURE_ACCEPTANCE_PROJECT_ID) is None:
        pages = tuple(
            PageItem(
                id=str(row["page_id"]),
                order=int(row["order"]),
                page_type=row["page_type"],
                title=str(row["title"]),
                body=str(row["body"]),
                visual_goal=str(row["visual_goal"]),
                template_id=str(row["template_id"]),
                heading_level=1 if row["page_type"] is PageType.HERO else 2,
                status=PageStatus.READY,
            )
            for row in AZURE_ACCEPTANCE_PAGES
        )
        plan = PagePlan(
            id="01696866-43ce-41bc-a86e-449aec690c83",
            project_id=AZURE_ACCEPTANCE_PROJECT_ID,
            version=3,
            items=pages,
            layout_library_id="library-square-2048",
            confirmed=True,
            created_at=created_at,
            updated_at=created_at,
        )
        repository.save_plan(
            plan,
            replace(project, status=ProjectStatus.COMPLETED, updated_at=created_at),
        )

    for row in AZURE_ACCEPTANCE_PAGES:
        order = int(row["order"])
        job_id = f"azure-five-page-acceptance-job-{order}"
        if production_repository.get_job(job_id) is not None:
            continue
        page_source = source_root / f"page-{order}"
        source_paths = {
            "base": page_source / "base.png",
            "text": page_source / "text.png",
            "composed": page_source / "composed.png",
        }
        if not all(path.is_file() for path in source_paths.values()):
            continue
        relative_root = Path("showcases") / "azure-five-page-acceptance" / f"page-{order}"
        destination_root = production_root / relative_root
        destination_root.mkdir(parents=True, exist_ok=True)
        for kind, source in source_paths.items():
            shutil.copy2(source, destination_root / f"{kind}.png")

        candidate_id = f"azure-five-page-acceptance-candidate-{order}"
        trace = {
            "stage": "completed",
            "progress": 100,
            "label": "仓库内置 Azure 验收快照已就绪",
            "plan_version": 3,
            "quality": "high",
            "prompt_version_id": "prompt-lifestyle-scene-v2",
            "bundled_azure_acceptance": True,
            "reference_count": 1,
            "reference_files": [product_reference.name],
            "image_elapsed_seconds": row["elapsed_seconds"],
        }
        job = GenerationJob(
            id=job_id,
            project_id=AZURE_ACCEPTANCE_PROJECT_ID,
            page_id=str(row["page_id"]),
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
            project_id=AZURE_ACCEPTANCE_PROJECT_ID,
            page_id=str(row["page_id"]),
            candidate_index=1,
            base_path=str(relative_root / "base.png"),
            text_layer_path=str(relative_root / "text.png"),
            composed_path=str(relative_root / "composed.png"),
            prompt="历史 Azure 2048 High 验收 Prompt；场景底图、商品层与确定性文字层按模板合成。",
            score=98,
            rank=1,
            status=CandidateStatus.GENERATED,
            metadata={
                "generator": {
                    "provider": "azure-gpt-image",
                    "requested_size": "2048x2048",
                    "actual_size": "2048x2048",
                    "quality": "high",
                    "reference_strategy": "layered_product",
                    "reference_count": 1,
                    "elapsed_seconds": row["elapsed_seconds"],
                    "layout": {
                        "template_id": row["template_id"],
                        "library_id": "library-square-2048",
                        "canvas_size": "2048x2048",
                    },
                },
                "composition": {
                    "post_composed": True,
                    "base_and_text_layer_are_separate_files": True,
                    "authoritative_title": row["title"],
                    "authoritative_body": row["body"],
                },
                "recipe_id": "commerce-lifestyle-demo-v1",
                "prompt_version_id": "prompt-lifestyle-scene-v2",
                "historical_acceptance": True,
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
                "historical_acceptance": True,
                "provider": "azure-ai-vision+azure-openai",
                "canvas_size": "2048x2048",
                "layout_library_id": "library-square-2048",
                "template_id": row["template_id"],
                "text_layer_source": "deterministic_composition",
                "reference_count": 1,
            },
            created_at=created_at,
        )
        production_repository.save_job_results(job, [candidate], [qa])
        production_repository.save_decision(
            ReviewDecision(
                id=f"{candidate_id}-approval",
                project_id=AZURE_ACCEPTANCE_PROJECT_ID,
                page_id=str(row["page_id"]),
                candidate_id=candidate_id,
                decision=ReviewDecisionType.APPROVED,
                override_reason="2026-08-11 Azure 五页验收通过，仓库内置历史快照",
                reviewer="codex-final-acceptance",
                created_at=created_at,
            )
        )
