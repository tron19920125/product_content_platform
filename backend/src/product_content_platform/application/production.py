from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from product_content_platform.domain import (
    AssetUsage,
    BatchItemStatus,
    BatchStatus,
    Candidate,
    CandidateStatus,
    DomainValidationError,
    EntityNotFoundError,
    FeatureGroup,
    GenerationJob,
    JobStatus,
    PromptVersion,
    ProjectStatus,
    PublishStatus,
    QAResult,
    QAStatus,
    Recipe,
    ReviewDecision,
    ReviewDecisionType,
    TextDocument,
    TextLayer,
    validate_image_quality,
)

from .platform import PlatformApplication
from .production_ports import ArchiveExporter, PageProductionEngine, ProductionRepository


BUILTIN_TEMPLATE_IDS = (
    "hero-center", "split-left", "split-right", "scene-overlay", "data-grid",
    "landscape-story-left-v1", "landscape-feature-band-v1", "landscape-editorial-right-v1",
    "portrait-story-top-v1", "portrait-feature-bottom-v1", "portrait-detail-stack-v1",
)


def now() -> datetime:
    return datetime.now(timezone.utc)


class ProductionApplication:
    """Orchestrates the complete production lifecycle behind one application interface."""

    def __init__(
        self,
        platform: PlatformApplication,
        repository: ProductionRepository,
        engine: PageProductionEngine,
        exporter: ArchiveExporter,
        resolve_asset: Any,
    ) -> None:
        self._platform = platform
        self._repository = repository
        self._engine = engine
        self._exporter = exporter
        self._resolve_asset = resolve_asset

    def seed_defaults(self, model: str = "local-preview") -> None:
        model_params = (
            {
                "quality": os.environ.get("PCP_IMAGE_QUALITY", "high"),
                "reference_strategy": "model_edit",
                "max_auto_regenerations": 1,
            }
            if model == "azure-gpt-image"
            else {
                "quality": "high",
                "reference_strategy": "model_edit",
                "max_auto_regenerations": 1,
            }
        )
        prompt = PromptVersion(
            id="prompt-commerce-v2",
            prompt_asset_id="prompt-commerce-detail",
            name="家电电商详情基础 Prompt",
            version=2,
            body=(
                "为{{product_name}}（{{model}}）制作电商详情视觉底图。"
                "视觉目标：{{visual_goal}}。{{composition_instruction}}。"
                "商品结构、型号和参考图中的外观必须保持准确。"
                "最终标题和正文由后期文字层统一排版，底图中不要生成任何文字。"
            ),
            variables=("product_name", "model", "visual_goal", "composition_instruction"),
            status=PublishStatus.PUBLISHED,
            change_note="P0 底图与文字分离版本",
        )
        recipe = Recipe(
            id="commerce-detail-v1",
            name="家电电商详情基础配方",
            status=PublishStatus.PUBLISHED,
            prompt_version_id=prompt.id,
            model=model,
            model_params=model_params,
            template_ids=BUILTIN_TEMPLATE_IDS,
            qa_policy="commerce-basic-v1",
            candidate_count=2,
        )
        self._repository.ensure_seed_data(prompt, recipe)
        demo_prompt = PromptVersion(
            id="prompt-lifestyle-scene-v3",
            prompt_asset_id="prompt-lifestyle-scene",
            name="高端生活方式多参考生成 Prompt",
            version=3,
            body=(
                "为{{product_name}}（{{model}}）制作具有完整环境叙事的高端电商广告图。"
                "页面视觉目标：{{visual_goal}}。"
                "场景应包含真实建筑空间、墙面与地面材质、自然光或柔和电影光、可信投影、"
                "与{{category}}使用情境相关的克制辅助陈设和前后景层次，避免只有纯白背景和孤立商品。"
                "模板场景建议：{{scene_prompt_hint}}。模板构图：{{composition_instruction}}。"
                "把输入的全部商品外观图和局部细节图视为同一件真实商品的多视角证据，直接在场景中"
                "重新生成一个完整商品；允许按页面目标调整拍摄角度、透视、环境反射和光影效果，但必须"
                "保持商品轮廓、比例、颜色、材质、门体、把手、控制面板和关键结构的一致性，不得把参考图"
                "当作平面贴纸粘贴，也不得拼出多个重复商品。最终营销标题和正文由独立文字层统一排版，"
                "生成图中不要新增营销文字、占位符或水印。"
            ),
            variables=(
                "product_name", "model", "category", "visual_goal",
                "scene_prompt_hint", "composition_instruction",
            ),
            status=PublishStatus.PUBLISHED,
            change_note="黄金演示：多参考图生成商品与场景，营销文字独立排版",
        )
        demo_recipe = Recipe(
            id="commerce-lifestyle-demo-v1",
            name="高端生活场景演示配方",
            status=PublishStatus.PUBLISHED,
            prompt_version_id=demo_prompt.id,
            model=model,
            model_params={
                "quality": "high",
                "reference_strategy": "model_edit",
                "max_auto_regenerations": 0,
            },
            template_ids=BUILTIN_TEMPLATE_IDS,
            qa_policy="commerce-basic-v1",
            candidate_count=1,
        )
        self._repository.ensure_seed_data(demo_prompt, demo_recipe)

    def list_prompt_versions(self) -> list[PromptVersion]:
        return self._repository.list_prompt_versions()

    def create_prompt_version(
        self,
        *,
        name: str,
        body: str,
        variables: Iterable[str],
        prompt_asset_id: str = "",
        change_note: str = "",
    ) -> PromptVersion:
        if not name.strip() or not body.strip():
            raise DomainValidationError("Prompt 名称和内容不能为空")
        asset_id = prompt_asset_id.strip() or str(uuid4())
        existing = [item for item in self._repository.list_prompt_versions() if item.prompt_asset_id == asset_id]
        version = max((item.version for item in existing), default=0) + 1
        prompt = PromptVersion(
            id=str(uuid4()), prompt_asset_id=asset_id, name=name.strip(), version=version,
            body=body.strip(), variables=tuple(dict.fromkeys(value.strip() for value in variables if value.strip())),
            status=PublishStatus.DRAFT, change_note=change_note.strip(),
        )
        self._repository.save_prompt_version(prompt)
        return prompt

    def publish_prompt(self, prompt_id: str) -> PromptVersion:
        current = self._get_prompt(prompt_id)
        published = replace(current, status=PublishStatus.PUBLISHED)
        # Prompt versions are immutable; publishing is represented by a new row only for new content.
        # The status mutation is intentionally persisted through the repository's focused helper.
        updater = getattr(self._repository, "update_prompt_status", None)
        if updater is None:
            raise DomainValidationError("当前存储 adapter 不支持发布 Prompt")
        updater(prompt_id, PublishStatus.PUBLISHED)
        return published

    def list_recipes(self, published_only: bool = False) -> list[Recipe]:
        recipes = self._repository.list_recipes()
        return [item for item in recipes if item.status is PublishStatus.PUBLISHED] if published_only else recipes

    def create_recipe(
        self,
        *,
        name: str,
        prompt_version_id: str,
        model: str,
        model_params: dict[str, Any],
        template_ids: Iterable[str],
        qa_policy: str,
        candidate_count: int,
    ) -> Recipe:
        self._get_prompt(prompt_version_id)
        if not name.strip() or not model.strip():
            raise DomainValidationError("配方名称和模型不能为空")
        quality = validate_image_quality(str(model_params.get("quality") or "high"))
        reference_strategy = str(model_params.get("reference_strategy") or "model_edit").strip()
        if reference_strategy not in {"model_edit", "layered_product"}:
            raise DomainValidationError("参考图策略必须是 model_edit 或 layered_product")
        try:
            max_auto_regenerations = int(model_params.get("max_auto_regenerations", 0))
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("自动图片修复次数必须是 0 或 1") from exc
        if max_auto_regenerations not in {0, 1}:
            raise DomainValidationError("自动图片修复次数必须是 0 或 1")
        templates = tuple(dict.fromkeys(value.strip() for value in template_ids if value.strip()))
        if not templates:
            raise DomainValidationError("配方至少需要一个模板")
        recipe = Recipe(
            id=str(uuid4()), name=name.strip(), status=PublishStatus.DRAFT,
            prompt_version_id=prompt_version_id, model=model.strip(),
            model_params={
                **dict(model_params),
                "quality": quality,
                "reference_strategy": reference_strategy,
                "max_auto_regenerations": max_auto_regenerations,
            },
            template_ids=templates, qa_policy=qa_policy.strip() or "commerce-basic-v1",
            candidate_count=max(1, min(3, candidate_count)),
        )
        self._repository.save_recipe(recipe)
        return recipe

    def publish_recipe(self, recipe_id: str) -> Recipe:
        recipe = self._get_recipe(recipe_id, published_required=False)
        prompt = self._get_prompt(recipe.prompt_version_id)
        if prompt.status is not PublishStatus.PUBLISHED:
            raise DomainValidationError("配方引用的 Prompt 版本尚未发布")
        published = replace(recipe, status=PublishStatus.PUBLISHED, updated_at=now())
        self._repository.save_recipe(published)
        return published

    def start_project(
        self,
        project_id: str,
        recipe_id: str = "commerce-detail-v1",
        force: bool = False,
        quality: str | None = None,
    ) -> list[GenerationJob]:
        project = self._platform.get_project(project_id)
        plan = self._platform.get_plan(project_id)
        if not plan.confirmed:
            raise DomainValidationError("页面规划确认后才能开始生产")
        recipe = self._get_recipe(recipe_id, published_required=True)
        unsupported_templates = sorted({page.template_id for page in plan.items} - set(recipe.template_ids))
        if unsupported_templates:
            raise DomainValidationError(
                f"当前配方不支持页面所选模板：{', '.join(unsupported_templates)}；请更换配方或把模板加入配方"
            )
        effective_quality = validate_image_quality(
            quality or str(recipe.model_params.get("quality") or "high")
        )
        existing = self._latest_jobs(project_id)
        if not force and existing and all(
            job.recipe_id == recipe_id and job.trace.get("plan_version") == plan.version
            and job.trace.get("quality") == effective_quality
            and job.status in {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.COMPLETED}
            for job in existing.values()
        ) and set(existing) == {page.id for page in plan.items}:
            return list(existing.values())
        reference_files = [
            asset.file_name
            for asset in self._platform.list_assets(project_id)
            if asset.mime_type.startswith("image/")
        ]
        jobs = [
            GenerationJob(
                id=str(uuid4()), project_id=project.id, page_id=page.id, recipe_id=recipe.id,
                status=JobStatus.QUEUED,
                trace={
                    "stage": "queued",
                    "plan_version": plan.version,
                    "prompt_version_id": recipe.prompt_version_id,
                    "recipe_default_quality": str(recipe.model_params.get("quality") or "high"),
                    "quality": effective_quality,
                    "quality_overridden": quality is not None,
                    "reference_count": len(reference_files),
                    "reference_files": reference_files,
                },
            )
            for page in plan.items
        ]
        self._invalidate_decisions(project_id, "页面规划或生产结果已更新")
        self._repository.create_jobs(jobs)
        self._platform.set_project_status(project_id, ProjectStatus.PRODUCING)
        return jobs

    def list_jobs(self, project_id: str | None = None) -> list[GenerationJob]:
        return self._repository.list_jobs(project_id)

    def regenerate_page(
        self,
        project_id: str,
        page_id: str,
        recipe_id: str = "commerce-detail-v1",
        quality: str | None = None,
    ) -> GenerationJob:
        project = self._platform.get_project(project_id)
        plan = self._platform.get_plan(project_id)
        if not plan.confirmed:
            raise DomainValidationError("页面规划确认后才能重新生成")
        if not any(page.id == page_id for page in plan.items):
            raise EntityNotFoundError(f"页面不存在: {page_id}")
        recipe = self._get_recipe(recipe_id, published_required=True)
        page = next(item for item in plan.items if item.id == page_id)
        if page.template_id not in recipe.template_ids:
            raise DomainValidationError(
                f"当前配方不支持页面所选模板：{page.template_id}；请更换配方或把模板加入配方"
            )
        effective_quality = validate_image_quality(
            quality or str(recipe.model_params.get("quality") or "high")
        )
        reference_files = [
            asset.file_name
            for asset in self._platform.list_assets(project_id)
            if asset.mime_type.startswith("image/")
        ]
        job = GenerationJob(
            id=str(uuid4()), project_id=project.id, page_id=page_id, recipe_id=recipe.id,
            status=JobStatus.QUEUED,
            trace={
                "stage": "queued",
                "plan_version": plan.version,
                "regeneration": True,
                "recipe_default_quality": str(recipe.model_params.get("quality") or "high"),
                "quality": effective_quality,
                "quality_overridden": quality is not None,
                "reference_count": len(reference_files),
                "reference_files": reference_files,
            },
        )
        self._invalidate_decisions(project_id, "页面已重新生成", page_ids={page_id})
        self._repository.create_jobs([job])
        self._platform.set_project_status(project_id, ProjectStatus.PRODUCING)
        return job

    def request_candidate_edit(
        self,
        candidate_id: str,
        instruction: str,
        *,
        quality: str | None = None,
    ) -> GenerationJob:
        source = self._repository.get_candidate(candidate_id)
        if source is None:
            raise EntityNotFoundError(f"候选不存在: {candidate_id}")
        normalized_instruction = " ".join(instruction.split()).strip()
        if len(normalized_instruction) < 3:
            raise DomainValidationError("请至少填写 3 个字的单图修改要求")
        if len(normalized_instruction) > 1000:
            raise DomainValidationError("单图修改要求不能超过 1000 字")
        if self._is_typography_only(normalized_instruction):
            raise DomainValidationError("这是一项文字或排版修改，请使用“调整文字排版”或修改内容规划，无需再次调用生图模型")
        source_job = self._repository.get_job(source.job_id)
        if source_job is None:
            raise EntityNotFoundError(f"候选来源任务不存在: {source.job_id}")
        project = self._platform.get_project(source.project_id)
        plan = self._platform.get_plan(source.project_id)
        if not plan.confirmed:
            raise DomainValidationError("页面规划确认后才能针对候选图继续修改")
        if not any(page.id == source.page_id for page in plan.items):
            raise EntityNotFoundError(f"页面不存在: {source.page_id}")
        recipe = self._get_recipe(source_job.recipe_id, published_required=True)
        effective_quality = validate_image_quality(
            quality
            or str((source.metadata.get("effective_generation") or {}).get("quality") or "")
            or str(recipe.model_params.get("quality") or "high")
        )
        job = GenerationJob(
            id=str(uuid4()), project_id=project.id, page_id=source.page_id,
            recipe_id=recipe.id, status=JobStatus.QUEUED, max_attempts=1,
            trace={
                "stage": "queued", "stage_label": "等待执行单图定向修改", "progress": 0,
                "plan_version": plan.version, "generation_kind": "candidate_edit",
                "source_candidate_id": source.id, "source_job_id": source.job_id,
                "instruction": normalized_instruction, "quality": effective_quality,
            },
        )
        self._repository.create_jobs([job])
        self._platform.set_project_status(project.id, ProjectStatus.PRODUCING)
        return job

    def recover_pending(self) -> list[str]:
        project_ids = sorted({job.project_id for job in self._repository.list_jobs() if job.status is JobStatus.QUEUED})
        for project_id in project_ids:
            self.process_project(project_id)
        return project_ids

    def recover_interrupted(self) -> list[str]:
        """Fail jobs whose worker disappeared during a service restart."""
        interrupted_at = now()
        latest: dict[tuple[str, str], GenerationJob] = {}
        for job in self._repository.list_jobs():
            latest.setdefault((job.project_id, job.page_id), job)
        project_ids = {
            job.project_id
            for job in latest.values()
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}
        }
        for job in latest.values():
            if (
                job.project_id not in project_ids
                or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}
            ):
                continue
            interrupted = replace(
                job,
                status=JobStatus.FAILED,
                error="生产服务重启导致本次任务中断，请点击“重试生产”。",
                trace={
                    **job.trace,
                    "stage": "interrupted",
                    "interrupted_at": interrupted_at.isoformat(),
                },
                updated_at=interrupted_at,
            )
            self._repository.update_job(interrupted)
        for project_id in project_ids:
            self._platform.set_project_status(project_id, ProjectStatus.REVIEWING)
            self._sync_batch_project(project_id, BatchItemStatus.FAILED)
        return sorted(project_ids)

    def process_project(self, project_id: str) -> dict[str, Any]:
        project = self._platform.get_project(project_id)
        plan = self._platform.get_plan(project_id)
        pages = {page.id: page for page in plan.items}
        jobs = self._latest_jobs(project_id)
        assets = self._platform.list_assets(project_id)
        product_assets = [
            asset for asset in assets
            if asset.mime_type.startswith("image/")
            and asset.usage in {AssetUsage.PRODUCT, AssetUsage.DETAIL}
        ]
        usage_order = {AssetUsage.PRODUCT: 0, AssetUsage.DETAIL: 1}
        product_assets.sort(key=lambda asset: (usage_order[asset.usage], asset.created_at, asset.id))
        reference_limit = self._reference_limit()
        selected_assets = product_assets[:reference_limit]
        reference_paths = [self._resolve_asset(asset.storage_path) for asset in selected_assets]
        omitted_reference_count = max(0, len(product_assets) - len(selected_assets))
        for page_id, job in jobs.items():
            if job.status is not JobStatus.QUEUED or page_id not in pages:
                continue
            self._process_job(
                job, project, pages[page_id], reference_paths,
                omitted_reference_count=omitted_reference_count,
            )
        latest = self._latest_jobs(project_id)
        snapshot = self.get_project_production(project_id)
        if snapshot["ready_for_export"]:
            self._platform.set_project_status(project_id, ProjectStatus.COMPLETED)
            snapshot = self.get_project_production(project_id)
        elif latest and (
            all(job.status is JobStatus.FAILED for job in latest.values())
            or any(job.status is JobStatus.COMPLETED for job in latest.values())
        ):
            self._platform.set_project_status(project_id, ProjectStatus.REVIEWING)
            snapshot = self.get_project_production(project_id)
        return snapshot

    def get_project_production(self, project_id: str) -> dict[str, Any]:
        project = self._platform.get_project(project_id)
        plan = self._platform.get_plan(project_id)
        all_jobs = self._repository.list_jobs(project_id)
        job_by_id = {job.id: job for job in all_jobs}
        jobs = self._latest_jobs(project_id)
        all_candidates = self._repository.list_candidates(project_id)
        active_job_ids = {job.id for job in jobs.values()}
        candidates = [item for item in all_candidates if item.job_id in active_job_ids]
        qa_results = {
            item.id: qa for item in candidates if (qa := self._repository.get_qa_result(item.id)) is not None
        }
        decisions = self._latest_decisions(project_id)
        pages: list[dict[str, Any]] = []
        for page in plan.items:
            job = jobs.get(page.id)
            page_candidates = sorted(
                [item for item in candidates if item.page_id == page.id], key=lambda item: item.rank
            )
            page_history = [item for item in all_candidates if item.page_id == page.id]
            if not page_candidates and job and job.trace.get("generation_kind") == "candidate_edit":
                source_id = str(job.trace.get("source_candidate_id") or "")
                source = next((item for item in page_history if item.id == source_id), None)
                if source:
                    page_candidates = sorted(
                        [item for item in page_history if item.job_id == source.job_id],
                        key=lambda item: item.rank,
                    )
            history_qa = {
                item.id: qa for item in page_history
                if (qa := self._repository.get_qa_result(item.id)) is not None
            }
            pages.append(
                {
                    "page": page,
                    "job": job,
                    "candidates": page_candidates,
                    "qa_results": {item.id: history_qa.get(item.id) for item in page_candidates},
                    "history": page_history,
                    "history_qa_results": history_qa,
                    "decision": decisions.get(page.id),
                }
            )
        return {
            "project": project,
            "plan": plan,
            "pages": pages,
            "ready_for_export": bool(pages) and all(
                row["decision"] is not None
                and row["decision"].decision is ReviewDecisionType.APPROVED
                and any(
                    candidate.id == row["decision"].candidate_id
                    and (source_job := job_by_id.get(candidate.job_id)) is not None
                    and int(source_job.trace.get("plan_version") or 0) == plan.version
                    for candidate in row["history"]
                )
                for row in pages
            ),
        }

    def review_candidate(
        self,
        candidate_id: str,
        decision: ReviewDecisionType,
        override_reason: str = "",
        reviewer: str = "local-user",
        skip_qa: bool = False,
    ) -> ReviewDecision:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise EntityNotFoundError(f"候选不存在: {candidate_id}")
        qa = self._repository.get_qa_result(candidate_id)
        if decision is ReviewDecisionType.APPROVED and qa is None and not skip_qa:
            raise DomainValidationError("该候选尚未执行质检；请先手动质检，或明确选择跳过质检后确认")
        if decision is ReviewDecisionType.APPROVED and qa is None and skip_qa and not override_reason.strip():
            raise DomainValidationError("跳过自动质检时必须填写人工确认说明，审计记录不会标记为质检通过")
        if decision is ReviewDecisionType.APPROVED and qa:
            blocking = [issue for issue in qa.issues if issue.get("severity") in {"P0", "P1"}]
            if blocking and not override_reason.strip():
                raise DomainValidationError("候选存在 P0/P1 问题，人工覆盖时必须填写原因")
        review = ReviewDecision(
            id=str(uuid4()), project_id=candidate.project_id, page_id=candidate.page_id,
            candidate_id=candidate.id, decision=decision,
            override_reason=override_reason.strip(), reviewer=reviewer.strip() or "local-user",
            qa_disposition="skipped_by_human" if qa is None and skip_qa else "qa_completed",
        )
        self._repository.save_decision(review)
        snapshot = self.get_project_production(candidate.project_id)
        if snapshot["ready_for_export"]:
            self._platform.set_project_status(candidate.project_id, ProjectStatus.COMPLETED)
            self._sync_batch_project(candidate.project_id, BatchItemStatus.COMPLETED)
        else:
            self._platform.set_project_status(candidate.project_id, ProjectStatus.REVIEWING)
            self._sync_batch_project(candidate.project_id, BatchItemStatus.NEEDS_REVIEW)
        return review

    def get_text_document(self, candidate_id: str) -> TextDocument:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise EntityNotFoundError(f"候选不存在: {candidate_id}")
        existing = self._repository.get_text_document(candidate_id)
        if existing is not None:
            feature_virtual_layer_ids = {
                f"{group.id}-{item.id}-{suffix}"
                for group in existing.feature_groups
                for item in group.items
                for suffix in ("title", "description")
            }
            if existing.feature_groups and any(
                layer.source == "feature_group" or layer.id in feature_virtual_layer_ids
                for layer in existing.layers
            ):
                cleaned = replace(
                    existing, version=existing.version + 1,
                    layers=tuple(
                        layer for layer in existing.layers
                        if layer.source != "feature_group" and layer.id not in feature_virtual_layer_ids
                    ),
                    ai_reasoning=(existing.ai_reasoning + " 已合并重复的卖点文字虚拟层。 ").strip(),
                )
                self._repository.save_text_document(cleaned)
                return cleaned
            if existing.version == 1 and existing.source == "ai":
                page = self._page(candidate.project_id, candidate.page_id)
                restored = self._engine.suggest_text_document(candidate=candidate, page=page)
                if restored.source == "candidate" and restored.layers != existing.layers:
                    restored = replace(restored, version=2)
                    self._repository.save_text_document(restored)
                    return restored
            return existing
        page = self._page(candidate.project_id, candidate.page_id)
        document = self._engine.suggest_text_document(candidate=candidate, page=page)
        self._repository.save_text_document(document)
        return document

    def save_text_document(
        self,
        candidate_id: str,
        *,
        layers: list[dict[str, Any]],
        feature_groups: list[dict[str, Any]] | None = None,
        base_version: int,
        source: str = "manual",
        ai_reasoning: str = "",
    ) -> TextDocument:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise EntityNotFoundError(f"候选不存在: {candidate_id}")
        current = self._repository.get_text_document(candidate_id)
        current_version = current.version if current else 0
        if base_version != current_version:
            raise DomainValidationError(f"文字图层已更新（当前 v{current_version}），请刷新后再保存")
        document = TextDocument(
            candidate_id=candidate_id, version=current_version + 1,
            layers=tuple(TextLayer.from_dict(value) for value in layers),
            feature_groups=tuple(
                FeatureGroup.from_dict(value) if isinstance(value, dict) else value
                for value in (
                    feature_groups if feature_groups is not None else (current.feature_groups if current else ())
                )
            ),
            source=source, ai_reasoning=ai_reasoning,
        )
        self._repository.save_text_document(document)
        return document

    def ai_layout_text_document(self, candidate_id: str, instruction: str = "") -> TextDocument:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise EntityNotFoundError(f"候选不存在: {candidate_id}")
        current = self._repository.get_text_document(candidate_id)
        page = self._page(candidate.project_id, candidate.page_id)
        document = self._engine.suggest_text_document(
            candidate=candidate, page=page, instruction=instruction, current=current,
        )
        self._repository.save_text_document(document)
        return document

    def regenerate_feature_icon(
        self,
        candidate_id: str,
        group_id: str,
        item_id: str,
        instruction: str = "",
    ) -> TextDocument:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise EntityNotFoundError(f"候选不存在: {candidate_id}")
        current = self.get_text_document(candidate_id)
        try:
            updated = self._engine.regenerate_feature_icon(
                document=current, group_id=group_id, item_id=item_id, instruction=instruction,
            )
        except (ValueError, FileNotFoundError) as exc:
            raise DomainValidationError(str(exc)) from exc
        saved = replace(updated, version=current.version + 1, source="manual")
        self._repository.save_text_document(saved)
        return saved

    def replace_feature_icon(
        self,
        candidate_id: str,
        group_id: str,
        item_id: str,
        content: bytes,
    ) -> TextDocument:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise EntityNotFoundError(f"候选不存在: {candidate_id}")
        current = self.get_text_document(candidate_id)
        try:
            updated = self._engine.replace_feature_icon(
                document=current, group_id=group_id, item_id=item_id, content=content,
            )
        except (ValueError, FileNotFoundError) as exc:
            raise DomainValidationError(str(exc)) from exc
        saved = replace(updated, version=current.version + 1, source="manual")
        self._repository.save_text_document(saved)
        return saved

    def feature_icon_file(self, candidate_id: str, group_id: str, item_id: str) -> Path:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise EntityNotFoundError(f"候选不存在: {candidate_id}")
        current = self.get_text_document(candidate_id)
        try:
            path = self._engine.resolve_feature_icon(current, group_id, item_id)
        except (ValueError, FileNotFoundError) as exc:
            raise EntityNotFoundError("图文卖点图标不存在") from exc
        if not path.exists():
            raise EntityNotFoundError("图文卖点图标文件不存在")
        return path

    def apply_text_document(self, candidate_id: str, version: int) -> Candidate:
        source = self._repository.get_candidate(candidate_id)
        if source is None:
            raise EntityNotFoundError(f"候选不存在: {candidate_id}")
        document = self._repository.get_text_document(candidate_id, version)
        if document is None:
            raise DomainValidationError("文字图层版本不存在")
        project = self._platform.get_project(source.project_id)
        plan = self._platform.get_plan(source.project_id)
        page = next((item for item in plan.items if item.id == source.page_id), None)
        if page is None:
            raise EntityNotFoundError(f"页面不存在: {source.page_id}")
        source_job = self._repository.get_job(source.job_id)
        if source_job is None:
            raise EntityNotFoundError("来源生产任务不存在")
        recipe = self._get_recipe(source_job.recipe_id, published_required=True)
        prompt = self._get_prompt(recipe.prompt_version_id)
        references = [
            self._resolve_asset(asset.storage_path)
            for asset in self._platform.list_assets(source.project_id)
            if asset.mime_type.startswith("image/")
        ]
        job = GenerationJob(
            id=str(uuid4()), project_id=source.project_id, page_id=source.page_id,
            recipe_id=recipe.id, status=JobStatus.COMPLETED, attempt=1,
            trace={
                "generation_kind": "text_document_apply", "stage": "completed", "progress": 100,
                "stage_label": "文字图层已应用，等待质检或人工确认", "plan_version": plan.version,
                "source_candidate_id": source.id, "source_text_document_version": document.version,
                "qa_execution": "not_run", "completed_at": now().isoformat(),
            },
        )
        self._repository.create_jobs([replace(job, status=JobStatus.RUNNING)])
        result = self._engine.recompose_document(
            project=project, page=page, recipe=recipe, prompt_version=prompt,
            source_candidate=source, text_document=document, reference_paths=references, run_qa=False,
        )
        candidate = Candidate(
            id=str(uuid4()), job_id=job.id, project_id=source.project_id, page_id=source.page_id,
            candidate_index=1, base_path=result.base_path, text_layer_path=result.text_layer_path,
            composed_path=result.composed_path, prompt=result.prompt, score=result.score, rank=1,
            status=CandidateStatus.NEEDS_REVIEW, metadata=result.metadata,
        )
        self._repository.save_job_results(job, [candidate], [])
        applied = TextDocument(
            candidate_id=candidate.id, version=1, layers=document.layers,
            feature_groups=document.feature_groups, status="applied",
            source=document.source, ai_reasoning=document.ai_reasoning,
        )
        self._repository.save_text_document(applied)
        self._invalidate_decisions(source.project_id, "文字图层已重新应用，需要重新确认", page_ids={source.page_id})
        self._platform.set_project_status(source.project_id, ProjectStatus.REVIEWING)
        return candidate

    def run_candidate_qa(self, candidate_id: str) -> QAResult:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise EntityNotFoundError(f"候选不存在: {candidate_id}")
        project = self._platform.get_project(candidate.project_id)
        page = self._page(candidate.project_id, candidate.page_id)
        source_job = self._repository.get_job(candidate.job_id)
        if source_job is None:
            raise EntityNotFoundError("候选生产任务不存在")
        recipe = self._get_recipe(source_job.recipe_id, published_required=True)
        prompt = self._get_prompt(recipe.prompt_version_id)
        references = [
            self._resolve_asset(asset.storage_path)
            for asset in self._platform.list_assets(candidate.project_id)
            if asset.mime_type.startswith("image/")
        ]
        result = self._engine.inspect_candidate(
            project=project, page=page, recipe=recipe, prompt_version=prompt,
            candidate=candidate, reference_paths=references,
        )
        qa = QAResult(
            id=str(uuid4()), candidate_id=candidate.id, status=QAStatus(result.qa_status),
            score=result.score, issues=result.issues, evidence=result.evidence,
            suggested_fix=result.suggested_fix, repair_applied=result.repair_applied,
        )
        self._repository.save_qa_result(qa)
        self._repository.update_candidate_status(
            candidate.id, CandidateStatus.GENERATED if qa.status is QAStatus.PASS else CandidateStatus.NEEDS_REVIEW,
        )
        return qa

    def _page(self, project_id: str, page_id: str) -> Any:
        plan = self._platform.get_plan(project_id)
        page = next((item for item in plan.items if item.id == page_id), None)
        if page is None:
            raise EntityNotFoundError(f"页面不存在: {page_id}")
        return page

    def candidate_file(self, candidate_id: str, kind: str) -> Path:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise EntityNotFoundError(f"候选不存在: {candidate_id}")
        relative_path = {
            "base": candidate.base_path,
            "text": candidate.text_layer_path,
            "composed": candidate.composed_path,
            "icons": str((candidate.metadata.get("composition") or {}).get("icon_layer_path") or ""),
        }.get(kind)
        if relative_path == "":
            relative_path = None
        if relative_path is None and kind in {"background", "product_layer"}:
            file_name = str((candidate.metadata.get("generator") or {}).get(f"{kind}_file") or "")
            if file_name and Path(file_name).name == file_name:
                relative_path = str(Path(candidate.base_path).parent / file_name)
        if relative_path is None:
            raise EntityNotFoundError(f"候选文件类型不存在: {kind}")
        return self._engine.resolve(relative_path)

    def recompose_page(
        self,
        project_id: str,
        page_id: str,
        *,
        source_candidate_id: str = "",
        typography: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self._platform.get_project(project_id)
        plan = self._platform.get_plan(project_id)
        page = next((item for item in plan.items if item.id == page_id), None)
        if page is None:
            raise EntityNotFoundError(f"页面不存在: {page_id}")
        latest_job = self._latest_jobs(project_id).get(page_id)
        if latest_job is None:
            raise DomainValidationError("页面尚未生成底图，不能仅重新排版")
        source_candidates = [
            item for item in self._repository.list_candidates(project_id, page_id)
            if item.job_id == latest_job.id
        ]
        if not source_candidates:
            raise DomainValidationError("页面没有可复用的底图")
        if source_candidate_id:
            source = next((item for item in source_candidates if item.id == source_candidate_id), None)
            if source is None:
                raise DomainValidationError("所选候选图不是本页当前可重新排版的结果")
        else:
            source = sorted(source_candidates, key=lambda item: item.rank)[0]
        recipe = self._get_recipe(latest_job.recipe_id, published_required=True)
        prompt = self._get_prompt(recipe.prompt_version_id)
        references = [
            self._resolve_asset(asset.storage_path)
            for asset in self._platform.list_assets(project_id)
            if asset.mime_type.startswith("image/")
        ]
        recomposition_started_at = now()
        job = GenerationJob(
            id=str(uuid4()), project_id=project_id, page_id=page_id, recipe_id=recipe.id,
            status=JobStatus.RUNNING, attempt=1,
            trace={
                "stage": "recomposing",
                "stage_label": "重新排版并执行质检",
                "progress": 10,
                "started_at": recomposition_started_at.isoformat(),
                "plan_version": plan.version,
                "source_candidate_id": source.id,
                "typography": dict(typography or {}),
                "reference_count": len(references),
                "reference_files": [path.name for path in references],
            },
        )
        self._repository.create_jobs([job])
        result = self._engine.recompose(
            project=project, page=page, recipe=recipe, prompt_version=prompt,
            source_candidate=source, reference_paths=references,
            typography=typography,
        )
        candidate_id = str(uuid4())
        candidate = Candidate(
            id=candidate_id, job_id=job.id, project_id=project_id, page_id=page_id,
            candidate_index=1, base_path=result.base_path, text_layer_path=result.text_layer_path,
            composed_path=result.composed_path, prompt=result.prompt, score=result.score, rank=1,
            status=CandidateStatus.GENERATED if result.qa_status == "pass" else CandidateStatus.NEEDS_REVIEW,
            metadata=result.metadata,
        )
        qa = QAResult(
            id=str(uuid4()), candidate_id=candidate_id, status=QAStatus(result.qa_status),
            score=result.score, issues=result.issues, evidence=result.evidence,
            suggested_fix=result.suggested_fix, repair_applied=result.repair_applied,
        )
        completed = replace(
            job, status=JobStatus.COMPLETED,
            trace={
                **job.trace,
                "stage": "completed",
                "stage_label": "重新排版与质检已完成",
                "progress": 100,
                "candidate_count": 1,
                "completed_at": now().isoformat(),
            }, updated_at=now(),
        )
        self._repository.save_job_results(completed, [candidate], [qa])
        self._invalidate_decisions(project_id, "文字重新排版后需要重新确认", page_ids={page_id})
        self._platform.set_project_status(project_id, ProjectStatus.REVIEWING)
        return self.get_project_production(project_id)

    def stitch_project(
        self,
        project_id: str,
        candidate_ids: list[str],
        *,
        direction: str,
        gap: int,
        background_color: str,
        alignment: str,
    ) -> Path:
        snapshot = self.get_project_production(project_id)
        if len(candidate_ids) < 2:
            raise DomainValidationError("长图拼接至少需要选择 2 张图片")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise DomainValidationError("同一张图片不能重复加入长图")
        available = {
            candidate.id: candidate
            for row in snapshot["pages"]
            for candidate in row["candidates"]
        }
        selected: list[Candidate] = []
        for candidate_id in candidate_ids:
            candidate = available.get(candidate_id)
            if candidate is None:
                raise DomainValidationError("所选图片不属于当前项目的有效生产结果")
            selected.append(candidate)
        project = snapshot["project"]
        try:
            return self._exporter.stitch(
                f"{project.profile.sku}_{project.name}_长图",
                [self._engine.resolve(candidate.composed_path) for candidate in selected],
                direction=direction,
                gap=gap,
                background_color=background_color,
                alignment=alignment,
            )
        except ValueError as exc:
            raise DomainValidationError(str(exc)) from exc

    def export_project(self, project_id: str) -> Path:
        snapshot = self.get_project_production(project_id)
        if not snapshot["ready_for_export"]:
            raise DomainValidationError("所有页面确认后才能导出正式结果")
        project = snapshot["project"]
        files, documents, manifest_pages = self._delivery_files(snapshot, prefix="")
        documents["project_summary.json"] = {
            "project_id": project.id,
            "project_name": project.name,
            "product_profile": project.profile.to_dict(),
            "pages": manifest_pages,
            "exported_at": now().isoformat(),
        }
        return self._exporter.create(f"{project.profile.sku}_{project.name}", files, documents)

    def create_recipe_from_project(self, project_id: str, name: str) -> Recipe:
        project = self._platform.get_project(project_id)
        snapshot = self.get_project_production(project_id)
        if not snapshot["ready_for_export"]:
            raise DomainValidationError("项目完成全部页面确认后才能沉淀配方")
        jobs = [row["job"] for row in snapshot["pages"] if row["job"] is not None]
        source_recipe = self._get_recipe(jobs[0].recipe_id, published_required=True)
        decisions = [row["decision"].candidate_id for row in snapshot["pages"]]
        selected_candidates = [
            candidate
            for candidate_id in decisions
            if (candidate := self._repository.get_candidate(candidate_id)) is not None
        ]
        runtime_models = {
            str((candidate.metadata.get("generator") or {}).get("provider") or "").strip()
            for candidate in selected_candidates
        }
        runtime_models.discard("")
        runtime_model = next(iter(runtime_models)) if len(runtime_models) == 1 else source_recipe.model
        recipe = Recipe(
            id=str(uuid4()), name=name.strip() or f"{project.profile.category} · {project.name} 配方",
            status=PublishStatus.DRAFT, prompt_version_id=source_recipe.prompt_version_id,
            model=runtime_model,
            model_params={
                **source_recipe.model_params,
                "example_project_id": project_id,
                "example_candidate_ids": decisions,
            },
            template_ids=tuple(dict.fromkeys(page.template_id for page in snapshot["plan"].items)),
            qa_policy=source_recipe.qa_policy, candidate_count=source_recipe.candidate_count,
        )
        self._repository.save_recipe(recipe)
        return recipe

    def start_batch(
        self,
        batch_id: str,
        recipe_id: str = "commerce-detail-v1",
        failed_only: bool = False,
        quality: str | None = None,
    ) -> dict[str, Any]:
        batch = self._platform.get_batch(batch_id)
        targets = [item for item in batch.items if not failed_only or item.status is BatchItemStatus.FAILED]
        if failed_only and not targets:
            raise DomainValidationError("批次中没有失败 SKU")
        self._platform.set_batch_status(batch_id, BatchStatus.RUNNING)
        for item in targets:
            try:
                item_recipe_id = str(item.override_config.get("recipe_id") or recipe_id)
                try:
                    plan = self._platform.get_plan(item.project_id)
                except EntityNotFoundError:
                    plan = self._platform.generate_plan(item.project_id)
                if not plan.confirmed:
                    plan = self._platform.save_plan(item.project_id, plan.items, confirmed=True)
                self.start_project(
                    item.project_id,
                    item_recipe_id,
                    force=failed_only,
                    quality=quality,
                )
                self._platform.set_batch_item_status(batch_id, item.id, BatchItemStatus.RUNNING)
            except Exception as exc:
                self._platform.set_batch_item_status(batch_id, item.id, BatchItemStatus.FAILED, str(exc))
        return self.batch_snapshot(batch_id)

    def process_batch(self, batch_id: str) -> dict[str, Any]:
        batch = self._platform.get_batch(batch_id)
        for item in batch.items:
            current = self._platform.get_batch(batch_id)
            if current.status is BatchStatus.PAUSED:
                break
            current_item = next(row for row in current.items if row.id == item.id)
            if current_item.status is not BatchItemStatus.RUNNING:
                continue
            try:
                snapshot = self.process_project(item.project_id)
                failed = any(row["job"] and row["job"].status is JobStatus.FAILED for row in snapshot["pages"])
                status = BatchItemStatus.FAILED if failed else BatchItemStatus.NEEDS_REVIEW
                self._platform.set_batch_item_status(batch_id, item.id, status, "生产任务失败" if failed else "")
            except Exception as exc:
                self._platform.set_batch_item_status(batch_id, item.id, BatchItemStatus.FAILED, str(exc))
        return self.batch_snapshot(batch_id)

    def pause_batch(self, batch_id: str) -> dict[str, Any]:
        self._platform.set_batch_status(batch_id, BatchStatus.PAUSED)
        return self.batch_snapshot(batch_id)

    def resume_batch(self, batch_id: str) -> dict[str, Any]:
        self._platform.set_batch_status(batch_id, BatchStatus.RUNNING)
        return self.batch_snapshot(batch_id)

    def batch_snapshot(self, batch_id: str) -> dict[str, Any]:
        batch = self._platform.get_batch(batch_id)
        return {
            "batch": batch,
            "items": [
                {"item": item, "project": self._platform.get_project(item.project_id)}
                for item in batch.items
            ],
        }

    def export_batch(self, batch_id: str) -> Path:
        batch = self._platform.get_batch(batch_id)
        files: dict[str, Path] = {}
        documents: dict[str, Any] = {}
        exported: list[str] = []
        skipped: list[dict[str, str]] = []
        for item in batch.items:
            try:
                snapshot = self.get_project_production(item.project_id)
                if not snapshot["ready_for_export"]:
                    raise DomainValidationError("尚未完成全部页面确认")
                prefix = f"{item.sku}/"
                item_files, item_documents, manifest_pages = self._delivery_files(snapshot, prefix=prefix)
                files.update(item_files)
                documents.update(item_documents)
                documents[f"{prefix}project_summary.json"] = {
                    "project_id": item.project_id, "sku": item.sku, "pages": manifest_pages,
                }
                exported.append(item.sku)
            except (DomainValidationError, EntityNotFoundError) as exc:
                skipped.append({"sku": item.sku, "reason": str(exc)})
        if not exported:
            raise DomainValidationError("批次中没有可正式导出的 SKU")
        documents["batch_summary.json"] = {
            "batch_id": batch.id, "batch_name": batch.name, "exported_skus": exported,
            "skipped_skus": skipped, "exported_at": now().isoformat(),
        }
        return self._exporter.create(f"batch_{batch.name}", files, documents)

    def _process_job(
        self,
        job: GenerationJob,
        project: Any,
        page: Any,
        reference_paths: list[Path],
        *,
        omitted_reference_count: int = 0,
    ) -> None:
        recipe = self._get_recipe(job.recipe_id, published_required=True)
        effective_quality = validate_image_quality(
            str(job.trace.get("quality") or recipe.model_params.get("quality") or "high")
        )
        recipe = replace(recipe, model_params={**recipe.model_params, "quality": effective_quality})
        prompt = self._get_prompt(recipe.prompt_version_id)
        current = job
        while current.attempt < current.max_attempts:
            attempt_started_at = now()
            current = replace(
                current, status=JobStatus.RUNNING, attempt=current.attempt + 1, error="",
                trace={
                    **current.trace,
                    "stage": "preparing",
                    "progress": 1,
                    "stage_label": "准备生产任务",
                    "started_at": current.trace.get("started_at") or attempt_started_at.isoformat(),
                    "attempt_started_at": attempt_started_at.isoformat(),
                    "reference_count": len(reference_paths),
                    "reference_files": [path.name for path in reference_paths],
                    "reference_limit": self._reference_limit(),
                    "omitted_reference_count": omitted_reference_count,
                },
                updated_at=attempt_started_at,
            )
            self._repository.update_job(current)

            def report_progress(stage: str, percent: int, details: dict[str, Any]) -> None:
                nonlocal current
                changed_at = now()
                history = list(current.trace.get("stage_history") or [])
                if not history or history[-1].get("stage") != stage:
                    history.append({
                        "stage": stage,
                        "progress": max(0, min(100, int(percent))),
                        "started_at": changed_at.isoformat(),
                    })
                stage_details = {
                    key: value for key, value in details.items()
                    if value is not None and key not in {"stage", "progress", "started_at"}
                }
                current = replace(
                    current,
                    trace={
                        **current.trace,
                        **stage_details,
                        "stage": stage,
                        "progress": max(0, min(100, int(percent))),
                        "stage_label": str(stage_details.get("label") or stage),
                        "stage_started_at": changed_at.isoformat(),
                        "stage_history": history,
                    },
                    updated_at=changed_at,
                )
                self._repository.update_job(current)

            try:
                if current.trace.get("generation_kind") == "candidate_edit":
                    source_id = str(current.trace.get("source_candidate_id") or "")
                    source_candidate = self._repository.get_candidate(source_id)
                    if source_candidate is None or source_candidate.project_id != project.id or source_candidate.page_id != page.id:
                        raise DomainValidationError("单图修改的来源候选不存在或不属于当前页面")
                    produced = [self._engine.edit_candidate(
                        project=project, page=page, recipe=recipe, prompt_version=prompt,
                        source_candidate=source_candidate,
                        instruction=str(current.trace.get("instruction") or ""),
                        quality=str(current.trace.get("quality") or "high"),
                        reference_paths=reference_paths,
                        progress=report_progress,
                    )]
                else:
                    produced = self._engine.execute(
                        project=project, page=page, recipe=recipe, prompt_version=prompt,
                        reference_paths=reference_paths,
                        progress=report_progress,
                    )
                candidates: list[Candidate] = []
                qa_results: list[QAResult] = []
                initial_text_documents: list[TextDocument] = []
                for result in produced:
                    generator_metadata = result.metadata.get("generator") or {}
                    generator_metadata["available_reference_count"] = (
                        len(reference_paths) + omitted_reference_count
                    )
                    generator_metadata["omitted_reference_count"] = omitted_reference_count
                    candidate_id = str(uuid4())
                    candidate = Candidate(
                        id=candidate_id, job_id=current.id, project_id=current.project_id,
                        page_id=current.page_id, candidate_index=result.candidate_index,
                        base_path=result.base_path, text_layer_path=result.text_layer_path,
                        composed_path=result.composed_path, prompt=result.prompt, score=result.score,
                        rank=result.rank,
                        status=CandidateStatus.GENERATED if result.qa_status == "pass" else CandidateStatus.NEEDS_REVIEW,
                        metadata=result.metadata,
                    )
                    candidates.append(candidate)
                    if (result.metadata.get("composition") or {}).get("text_layers"):
                        initial_text_documents.append(
                            self._engine.suggest_text_document(candidate=candidate, page=page)
                        )
                    qa_results.append(
                        QAResult(
                            id=str(uuid4()), candidate_id=candidate_id, status=QAStatus(result.qa_status),
                            score=result.score, issues=result.issues, evidence=result.evidence,
                            suggested_fix=result.suggested_fix, repair_applied=result.repair_applied,
                        )
                    )
                completed = replace(
                    current, status=JobStatus.COMPLETED,
                    trace={
                        **current.trace,
                        "stage": "completed",
                        "stage_label": (
                            "单图定向修改与质检已完成"
                            if current.trace.get("generation_kind") == "candidate_edit"
                            else "生成与质检已完成"
                        ),
                        "progress": 100,
                        "candidate_count": len(candidates),
                        "completed_at": now().isoformat(),
                    },
                    updated_at=now(),
                )
                self._repository.save_job_results(completed, candidates, qa_results)
                for document in initial_text_documents:
                    self._repository.save_text_document(document)
                if current.trace.get("generation_kind") == "candidate_edit":
                    self._invalidate_decisions(
                        project.id, "候选图完成定向修改后需要重新确认", page_ids={page.id}
                    )
                return
            except Exception as exc:
                current = replace(
                    current, status=JobStatus.FAILED, error=str(exc),
                    trace={
                        **current.trace,
                        "stage": "failed",
                        "stage_label": "生产失败",
                        "failed_at": now().isoformat(),
                    }, updated_at=now(),
                )
                self._repository.update_job(current)
                if current.attempt >= current.max_attempts:
                    return

    @staticmethod
    def _reference_limit() -> int:
        try:
            configured = int(os.environ.get("PCP_MAX_IMAGE_REFERENCES", "6"))
        except ValueError:
            configured = 6
        return max(1, min(16, configured))

    @staticmethod
    def _is_typography_only(instruction: str) -> bool:
        typography_terms = {
            "文字", "文案", "标题", "正文", "字体", "字号", "颜色", "行距", "字距",
            "排版", "对齐", "加粗", "标点", "句号", "逗号", "文本", "换行",
        }
        visual_terms = {
            "背景", "场景", "商品", "产品", "角度", "光线", "光影", "材质", "颜色氛围",
            "构图", "镜头", "透视", "道具", "家具", "环境", "阴影", "反射", "门", "效果",
        }
        return any(term in instruction for term in typography_terms) and not any(
            term in instruction for term in visual_terms
        )

    def _delivery_files(self, snapshot: dict[str, Any], prefix: str) -> tuple[dict[str, Path], dict[str, Any], list[dict[str, Any]]]:
        files: dict[str, Path] = {}
        documents: dict[str, Any] = {}
        manifest_pages: list[dict[str, Any]] = []
        for row in snapshot["pages"]:
            page = row["page"]
            decision = row["decision"]
            candidate = self._repository.get_candidate(decision.candidate_id)
            qa = self._repository.get_qa_result(candidate.id) if candidate else None
            if candidate is None or qa is None:
                raise DomainValidationError(f"第 {page.order} 页缺少已确认候选或质检记录")
            page_dir = f"{prefix}pages/{page.order:02d}_{page.page_type.value}"
            files[f"{page_dir}/final.png"] = self._engine.resolve(candidate.composed_path)
            files[f"{page_dir}/base.png"] = self._engine.resolve(candidate.base_path)
            files[f"{page_dir}/text_layer.png"] = self._engine.resolve(candidate.text_layer_path)
            layer_files = ["base.png", "text_layer.png", "final.png"]
            composition = candidate.metadata.get("composition") or {}
            icon_layer_path = str(composition.get("icon_layer_path") or "")
            if icon_layer_path:
                resolved_icon_layer = self._engine.resolve(icon_layer_path)
                if resolved_icon_layer.exists():
                    files[f"{page_dir}/icon_layer.png"] = resolved_icon_layer
                    layer_files.insert(-1, "icon_layer.png")
            icon_generation = composition.get("icon_generation") or {}
            icon_rows = list(icon_generation.get("icons") or [])
            icon_rows.extend(
                item
                for group in (composition.get("feature_groups") or [])
                if isinstance(group, dict)
                for item in (group.get("items") or [])
                if isinstance(item, dict)
            )
            exported_icon_paths: set[str] = set()
            for icon in icon_rows:
                icon_path = str(icon.get("path") or "") if isinstance(icon, dict) else ""
                icon_path = icon_path or (str(icon.get("icon_path") or "") if isinstance(icon, dict) else "")
                if not icon_path or icon_path in exported_icon_paths:
                    continue
                resolved_icon = self._engine.resolve(icon_path)
                if resolved_icon.exists():
                    icon_name = Path(icon_path).name
                    files[f"{page_dir}/icons/{icon_name}"] = resolved_icon
                    exported_icon_paths.add(icon_path)
            generator = candidate.metadata.get("generator") or {}
            for kind in ("background", "product_layer"):
                file_name = str(generator.get(f"{kind}_file") or "")
                if file_name and Path(file_name).name == file_name:
                    extra_path = self._engine.resolve(str(Path(candidate.base_path).parent / file_name))
                    if extra_path.exists():
                        files[f"{page_dir}/{file_name}"] = extra_path
                        layer_files.insert(0, file_name)
            documents[f"{page_dir}/qa.json"] = self._qa_payload(qa)
            effective_generation = candidate.metadata.get("effective_generation") or {
                "size": generator.get("requested_size") or generator.get("actual_size") or "",
                "quality": generator.get("quality") or "",
                "template_id": (generator.get("layout") or {}).get("template_id") or page.template_id,
                "reference_strategy": generator.get("reference_strategy") or "",
                "max_auto_regenerations": int(
                    (candidate.metadata.get("model_params") or {}).get("max_auto_regenerations", 0)
                ),
            }
            manifest_pages.append({
                "page_id": page.id, "order": page.order, "page_type": page.page_type.value,
                "title": page.title, "candidate_id": candidate.id, "score": candidate.score,
                "qa_status": qa.status.value, "prompt": candidate.prompt,
                "recipe_id": candidate.metadata.get("recipe_id", ""),
                "prompt_version_id": candidate.metadata.get("prompt_version_id", ""),
                "model": candidate.metadata.get("model", ""),
                "generator_provider": generator.get("provider", ""),
                "effective_generation": effective_generation,
                "layer_files": layer_files,
                "feature_groups": composition.get("feature_groups") or [],
                "icon_generation": icon_generation,
                "override_reason": decision.override_reason,
            })
        return files, documents, manifest_pages

    def _latest_jobs(self, project_id: str) -> dict[str, GenerationJob]:
        latest: dict[str, GenerationJob] = {}
        for job in self._repository.list_jobs(project_id):
            latest.setdefault(job.page_id, job)
        return latest

    def _latest_decisions(self, project_id: str) -> dict[str, ReviewDecision]:
        latest: dict[str, ReviewDecision] = {}
        for decision in self._repository.list_decisions(project_id):
            latest.setdefault(decision.page_id, decision)
        return latest

    def _sync_batch_project(self, project_id: str, status: BatchItemStatus) -> None:
        for batch in self._platform.list_batches():
            item = next((row for row in batch.items if row.project_id == project_id), None)
            if item:
                self._platform.set_batch_item_status(batch.id, item.id, status)

    def _invalidate_decisions(self, project_id: str, reason: str, page_ids: set[str] | None = None) -> None:
        for page_id, decision in self._latest_decisions(project_id).items():
            if decision.decision is not ReviewDecisionType.APPROVED:
                continue
            if page_ids is not None and page_id not in page_ids:
                continue
            self._repository.save_decision(
                ReviewDecision(
                    id=str(uuid4()), project_id=project_id, page_id=page_id,
                    candidate_id=decision.candidate_id, decision=ReviewDecisionType.REJECTED,
                    override_reason=reason, reviewer="system",
                )
            )

    def _get_prompt(self, prompt_id: str) -> PromptVersion:
        prompt = self._repository.get_prompt_version(prompt_id)
        if prompt is None:
            raise EntityNotFoundError(f"Prompt 版本不存在: {prompt_id}")
        return prompt

    def _get_recipe(self, recipe_id: str, published_required: bool) -> Recipe:
        recipe = self._repository.get_recipe(recipe_id)
        if recipe is None:
            raise EntityNotFoundError(f"配方不存在: {recipe_id}")
        if published_required and recipe.status is not PublishStatus.PUBLISHED:
            raise DomainValidationError("生产任务只能使用已发布配方")
        return recipe

    @staticmethod
    def _qa_payload(qa: QAResult) -> dict[str, Any]:
        return {
            "id": qa.id, "status": qa.status.value, "score": qa.score,
            "issues": list(qa.issues), "evidence": qa.evidence,
            "suggested_fix": qa.suggested_fix, "repair_applied": qa.repair_applied,
        }
