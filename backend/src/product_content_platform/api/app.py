from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from product_content_platform.adapters import (
    FixedContentCatalog,
    AzureImageGenerator,
    ProductQualityToolkit,
    LocalArchiveExporter,
    LocalAssetStore,
    LocalBaseImageGenerator,
    LocalProductionEngine,
    SkuImportParser,
    SQLitePlatformRepository,
    SQLiteProductionRepository,
    seed_showcase_projects,
)
from product_content_platform.application import (
    BatchSkuInput,
    PlatformApplication,
    PlanningApplication,
    ProductionApplication,
    ProjectInput,
)
from product_content_platform.domain import (
    Asset,
    AssetUsage,
    Batch,
    BatchItemStatus,
    Candidate,
    DomainValidationError,
    EntityNotFoundError,
    GenerationJob,
    PageItem,
    PagePlan,
    PageStatus,
    PageType,
    ProductProfile,
    Project,
    PromptVersion,
    QAResult,
    Recipe,
    ReviewDecision,
    ReviewDecisionType,
)
from product_content_platform.settings import Settings
from product_content_platform.planning import ContentPlanner
from product_content_platform.integrations.azure_preflight import run_preflight


class ProductProfilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    model: str = ""
    selling_points: list[str] = Field(default_factory=list)
    parameters: dict[str, str] = Field(default_factory=dict)
    reference_assets: list[str] = Field(default_factory=list)
    brand_requirements: str = ""
    output_requirements: str = ""

    def to_domain(self) -> ProductProfile:
        return ProductProfile.from_dict(self.model_dump())


class ProjectCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(min_length=1)
    profile: ProductProfilePayload


class ProjectUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str = ""
    profile: ProductProfilePayload


class BatchSkuPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: ProductProfilePayload
    override_config: dict[str, Any] = Field(default_factory=dict)


class BatchCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    common_config: dict[str, Any] = Field(default_factory=dict)
    skus: list[BatchSkuPayload] = Field(min_length=1)


class BatchItemStatusPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: BatchItemStatus
    error: str = ""


class PageItemPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    order: int = Field(ge=1)
    page_type: PageType
    title: str = Field(min_length=1)
    body: str = ""
    visual_goal: str = ""
    template_id: str = Field(min_length=1)
    heading_level: int = Field(default=1, ge=1, le=5)
    status: PageStatus = PageStatus.DRAFT

    def to_domain(self) -> PageItem:
        return PageItem(**self.model_dump())


class PagePlanUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PageItemPayload] = Field(min_length=1)
    layout_library_id: str | None = None
    confirmed: bool = False


class PagePlanGeneratePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layout_library_id: str = "library-square-2048"


class PlanningApplyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_fields: dict[str, list[str]] | None = None


class PromptCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    body: str = Field(min_length=1)
    variables: list[str] = Field(default_factory=list)
    prompt_asset_id: str = ""
    change_note: str = ""


class RecipeCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    prompt_version_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    model_params: dict[str, Any] = Field(default_factory=dict)
    template_ids: list[str] = Field(min_length=1)
    qa_policy: str = "commerce-basic-v1"
    candidate_count: int = Field(default=2, ge=1, le=3)


class TemplateCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    page_types: list[str] = Field(min_length=1)
    base_template_id: str = Field(min_length=1)
    size: str = Field(min_length=3)


class LayoutLibraryCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    size: str = Field(min_length=3)
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class TemplateDraftCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    page_types: list[str] = Field(min_length=1)
    base_template_id: str = ""
    title_box: list[float] | None = None
    body_box: list[float] | None = None
    product_box: list[float] | None = None
    product_anchor_box: list[float] | None = None
    safe_area_box: list[float] | None = None
    scene_prompt_hint: str = ""


class TemplateDraftUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    page_types: list[str] | None = None
    title_box: list[float] | None = None
    body_box: list[float] | None = None
    product_box: list[float] | None = None
    product_anchor_box: list[float] | None = None
    safe_area_box: list[float] | None = None
    scene_prompt_hint: str | None = None


class ProductionStartPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str = "commerce-detail-v1"
    force: bool = False
    quality: str | None = None


class TypographyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    font_family: str = Field(default="system_sans", pattern=r"^system_(sans|bold|serif)$")
    title_font_size: int | None = Field(default=None, ge=24, le=512)
    body_font_size: int | None = Field(default=None, ge=16, le=320)
    title_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    body_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    text_align: str = Field(default="left", pattern=r"^(left|center|right)$")
    vertical_align: str = Field(default="top", pattern=r"^(top|center|bottom)$")
    offset_x: int = Field(default=0, ge=-512, le=512)
    offset_y: int = Field(default=0, ge=-512, le=512)
    title_line_spacing: int | None = Field(default=None, ge=0, le=128)
    body_line_spacing: int | None = Field(default=None, ge=0, le=128)
    title_body_gap: int | None = Field(default=None, ge=0, le=256)


class RecomposePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_candidate_id: str = ""
    typography: TypographyPayload = Field(default_factory=TypographyPayload)


class CandidateEditPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=3, max_length=1000)
    quality: str | None = Field(default=None, pattern=r"^(low|medium|high)$")


class StitchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ids: list[str] = Field(min_length=2, max_length=50)
    direction: str = Field(default="vertical", pattern=r"^(vertical|horizontal)$")
    gap: int = Field(default=0, ge=0, le=128)
    background_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    alignment: str = Field(default="center", pattern=r"^(start|center|end)$")


class ReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ReviewDecisionType
    override_reason: str = ""
    reviewer: str = "local-user"


class RecipeCandidatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""


def create_app(
    *,
    database_path: Path | None = None,
    asset_root: Path | None = None,
    production_root: Path | None = None,
    export_root: Path | None = None,
) -> FastAPI:
    settings = Settings.from_environment()
    effective_database = database_path or settings.database_path
    repository = SQLitePlatformRepository(effective_database)
    platform = PlatformApplication(repository)
    effective_asset_root = asset_root or (effective_database.parent / "assets" if database_path else settings.asset_root)
    effective_production_root = production_root or (effective_database.parent / "production" if database_path else settings.production_root)
    effective_export_root = export_root or (effective_database.parent / "exports" if database_path else settings.export_root)
    assets = LocalAssetStore(effective_asset_root)
    imports = SkuImportParser()
    catalog = FixedContentCatalog(effective_database.parent / "templates.json")
    production_repository = SQLiteProductionRepository(effective_database)
    generator = (
        AzureImageGenerator()
        if settings.generation_mode == "azure"
        else LocalBaseImageGenerator()
    )
    engine = LocalProductionEngine(
        effective_production_root,
        generator,
        ProductQualityToolkit(mode=settings.qa_mode),
        template_resolver=catalog.template,
    )
    exporter = LocalArchiveExporter(effective_export_root)
    production = ProductionApplication(
        platform, production_repository, engine, exporter, assets.resolve
    )
    planning = PlanningApplication(
        platform, repository, ContentPlanner(settings.planning_mode), assets.resolve
    )
    production.seed_defaults("azure-gpt-image" if settings.generation_mode == "azure" else "local-preview")
    if database_path is None:
        seed_showcase_projects(
            source_root=Path(__file__).resolve().parents[4] / "examples" / "showcases",
            production_root=effective_production_root,
            repository=repository,
            platform=platform,
            production_repository=production_repository,
            asset_store=assets,
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        production.recover_interrupted()
        yield

    app = FastAPI(title="Product Content Platform", version="0.1.0", lifespan=lifespan)
    app.state.platform = platform
    app.state.assets = assets
    app.state.production = production
    app.state.planning = planning
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/preflight")
    def preflight() -> dict[str, Any]:
        return run_preflight(settings)

    @app.post("/api/projects", status_code=201)
    def create_project(payload: ProjectCreatePayload) -> dict[str, Any]:
        try:
            project = platform.create_project(
                ProjectInput(project_name=payload.project_name, profile=payload.profile.to_domain())
            )
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return project_to_dict(project)

    @app.post("/api/demo-projects/laundry", status_code=201)
    def create_laundry_demo_project() -> dict[str, Any]:
        project, plan = platform.create_laundry_demo_project()
        return {
            "project": project_to_dict(project),
            "plan": plan_to_dict(plan),
            "recipe_id": "commerce-lifestyle-demo-v1",
            "quality": "high",
            "required_next_step": "上传并绑定一张商品参考图，然后开始生产。",
        }

    @app.get("/api/projects")
    def list_projects() -> list[dict[str, Any]]:
        return [project_to_dict(project) for project in platform.list_projects()]

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        try:
            return project_to_dict(platform.get_project(project_id))
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/projects/{project_id}")
    def update_project(project_id: str, payload: ProjectUpdatePayload) -> dict[str, Any]:
        try:
            return project_to_dict(platform.update_project(project_id, payload.profile.to_domain(), payload.project_name))
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/clone", status_code=201)
    def clone_project(project_id: str) -> dict[str, Any]:
        try:
            return project_to_dict(platform.clone_project(project_id))
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/assets", status_code=201)
    async def upload_project_asset(
        project_id: str,
        request: Request,
        file_name: str = Query(min_length=1),
        usage: AssetUsage = AssetUsage.PRODUCT,
        source: str = Query(default="user_upload", min_length=1, max_length=80),
        authorization_status: str = Query(default="unconfirmed", pattern="^(unconfirmed|authorized|restricted)$"),
    ) -> dict[str, Any]:
        content = await request.body()
        try:
            platform.get_project(project_id)
            storage_path = assets.save(file_name, content)
            asset = platform.register_asset(
                project_id,
                usage,
                file_name,
                request.headers.get("content-type", "application/octet-stream"),
                storage_path,
                len(content),
                source,
                authorization_status,
            )
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return asset_to_dict(asset)

    @app.get("/api/projects/{project_id}/assets")
    def list_project_assets(project_id: str) -> list[dict[str, Any]]:
        try:
            return [asset_to_dict(asset) for asset in platform.list_assets(project_id)]
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/assets/{asset_id}/content")
    def get_asset_content(asset_id: str) -> FileResponse:
        try:
            asset = platform.get_asset(asset_id)
            path = assets.resolve(asset.storage_path)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return FileResponse(path, media_type=asset.mime_type, filename=asset.file_name)

    @app.post("/api/projects/{project_id}/plan", status_code=201)
    def generate_project_plan(project_id: str, payload: PagePlanGeneratePayload | None = None) -> dict[str, Any]:
        try:
            library_id = payload.layout_library_id if payload else "library-square-2048"
            catalog.library(library_id)
            library_templates = catalog.templates(library_id=library_id)
            template_ids: dict[PageType, str] = {}
            for page_type in PageType:
                matching = next((item for item in library_templates if page_type.value in item["page_types"]), None)
                if matching is None:
                    matching = library_templates[0] if library_templates else None
                if matching is not None:
                    template_ids[page_type] = matching["id"]
            if not template_ids:
                raise DomainValidationError("版式库中没有已发布模板")
            return plan_to_dict(platform.generate_plan(project_id, library_id, template_ids))
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/planning-runs", status_code=202)
    def start_planning_run(
        project_id: str,
        payload: PagePlanGeneratePayload,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        try:
            catalog.library(payload.layout_library_id)
            templates = catalog.templates(library_id=payload.layout_library_id)
            run = planning.start(project_id, payload.layout_library_id, templates)
            background_tasks.add_task(planning.process, run.id)
            return planning_run_to_dict(run)
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/planning-runs")
    def list_planning_runs(project_id: str) -> list[dict[str, Any]]:
        try:
            return [planning_run_to_dict(item) for item in planning.list(project_id)]
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/planning-runs/{run_id}")
    def get_planning_run(project_id: str, run_id: str) -> dict[str, Any]:
        try:
            run = planning.get(run_id)
            if run.project_id != project_id:
                raise EntityNotFoundError(f"内容规划运行不存在: {run_id}")
            return planning_run_to_dict(run)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/planning-runs/{run_id}/apply")
    def apply_planning_run(project_id: str, run_id: str, payload: PlanningApplyPayload) -> dict[str, Any]:
        try:
            return plan_to_dict(planning.apply(project_id, run_id, payload.selected_fields))
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/planning-runs/{run_id}/dismiss")
    def dismiss_planning_run(project_id: str, run_id: str) -> dict[str, Any]:
        try:
            return planning_run_to_dict(planning.dismiss(project_id, run_id))
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/plan")
    def get_project_plan(project_id: str) -> dict[str, Any]:
        try:
            return plan_to_dict(platform.get_plan(project_id))
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/projects/{project_id}/plan")
    def save_project_plan(project_id: str, payload: PagePlanUpdatePayload) -> dict[str, Any]:
        library_id = payload.layout_library_id
        if library_id is None:
            template_library_by_id = {item["id"]: item["library_id"] for item in catalog.templates()}
            inferred_libraries = {
                template_library_by_id[item.template_id]
                for item in payload.items
                if item.template_id in template_library_by_id
            }
            if len(inferred_libraries) != 1:
                raise HTTPException(status_code=422, detail="旧版请求中的模板必须全部属于同一个版式库")
            library_id = inferred_libraries.pop()
        try:
            catalog.library(library_id)
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        template_by_id = {item["id"]: item for item in catalog.templates(library_id=library_id)}
        template_ids = set(template_by_id)
        unknown = sorted({item.template_id for item in payload.items if item.template_id not in template_ids})
        if unknown:
            raise HTTPException(status_code=422, detail=f"模板不属于当前版式库或尚未发布: {', '.join(unknown)}")
        incompatible = sorted(
            item.template_id
            for item in payload.items
            if item.page_type.value not in template_by_id[item.template_id]["page_types"]
        )
        if incompatible:
            raise HTTPException(status_code=422, detail=f"模板不支持所选页面类型: {', '.join(incompatible)}")
        try:
            return plan_to_dict(
                platform.save_plan(
                    project_id,
                    [item.to_domain() for item in payload.items],
                    payload.confirmed,
                    library_id,
                )
            )
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/layout-libraries")
    def list_layout_libraries() -> list[dict[str, Any]]:
        return catalog.libraries()

    @app.get("/api/layout-libraries/{library_id}")
    def get_layout_library(library_id: str) -> dict[str, Any]:
        try:
            return catalog.library(library_id)
        except DomainValidationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/layout-libraries", status_code=201)
    def create_layout_library(payload: LayoutLibraryCreatePayload) -> dict[str, Any]:
        try:
            return catalog.create_library(**payload.model_dump())
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/templates")
    def list_templates(library_id: str | None = None, include_drafts: bool = False) -> list[dict[str, Any]]:
        try:
            return catalog.templates(library_id=library_id, include_drafts=include_drafts)
        except DomainValidationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/templates", status_code=201)
    def create_template(payload: TemplateCreatePayload) -> dict[str, Any]:
        try:
            return catalog.create_template(**payload.model_dump())
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/layout-libraries/{library_id}/templates", status_code=201)
    def create_template_draft(library_id: str, payload: TemplateDraftCreatePayload) -> dict[str, Any]:
        try:
            return catalog.create_template_draft(library_id=library_id, **payload.model_dump())
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.put("/api/templates/{template_id}")
    def update_template_draft(template_id: str, payload: TemplateDraftUpdatePayload) -> dict[str, Any]:
        try:
            return catalog.update_template_draft(template_id, **payload.model_dump(exclude_none=True))
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/templates/{template_id}", status_code=204)
    def delete_template_draft(template_id: str) -> Response:
        try:
            catalog.delete_template_draft(template_id)
            return Response(status_code=204)
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/templates/{template_id}/new-version", status_code=201)
    def create_template_version(template_id: str) -> dict[str, Any]:
        try:
            return catalog.create_next_version(template_id)
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/templates/{template_id}/publish")
    def publish_template(template_id: str) -> dict[str, Any]:
        try:
            return catalog.publish_template(template_id)
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/image-capabilities")
    def get_image_capabilities() -> dict[str, Any]:
        return catalog.capabilities()

    @app.get("/api/recipes")
    def list_recipes(published_only: bool = False) -> list[dict[str, Any]]:
        return [recipe_to_dict(item) for item in production.list_recipes(published_only)]

    @app.post("/api/recipes", status_code=201)
    def create_recipe(payload: RecipeCreatePayload) -> dict[str, Any]:
        known_template_ids = {item["id"] for item in catalog.templates()}
        unknown_templates = sorted(set(payload.template_ids) - known_template_ids)
        if unknown_templates:
            raise HTTPException(status_code=422, detail=f"未知模板: {', '.join(unknown_templates)}")
        try:
            recipe = production.create_recipe(**payload.model_dump())
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return recipe_to_dict(recipe)

    @app.post("/api/recipes/{recipe_id}/publish")
    def publish_recipe(recipe_id: str) -> dict[str, Any]:
        try:
            return recipe_to_dict(production.publish_recipe(recipe_id))
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/prompts")
    def list_prompts() -> list[dict[str, Any]]:
        return [prompt_to_dict(item) for item in production.list_prompt_versions()]

    @app.post("/api/prompts", status_code=201)
    def create_prompt(payload: PromptCreatePayload) -> dict[str, Any]:
        try:
            return prompt_to_dict(production.create_prompt_version(**payload.model_dump()))
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/prompts/{prompt_id}/publish")
    def publish_prompt(prompt_id: str) -> dict[str, Any]:
        try:
            return prompt_to_dict(production.publish_prompt(prompt_id))
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/production/start", status_code=202)
    def start_project_production(
        project_id: str,
        payload: ProductionStartPayload,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        try:
            jobs = production.start_project(
                project_id,
                payload.recipe_id,
                payload.force,
                quality=payload.quality,
            )
            background_tasks.add_task(production.process_project, project_id)
            return {"project_id": project_id, "jobs": [job_to_dict(job) for job in jobs]}
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/production")
    def get_project_production(project_id: str) -> dict[str, Any]:
        try:
            return production_snapshot_to_dict(production.get_project_production(project_id))
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/pages/{page_id}/recompose")
    def recompose_page(
        project_id: str,
        page_id: str,
        payload: RecomposePayload | None = None,
    ) -> dict[str, Any]:
        try:
            return production_snapshot_to_dict(production.recompose_page(
                project_id,
                page_id,
                source_candidate_id=payload.source_candidate_id if payload else "",
                typography=payload.typography.model_dump(exclude_none=True) if payload else None,
            ))
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/pages/{page_id}/regenerate", status_code=202)
    def regenerate_page(
        project_id: str,
        page_id: str,
        payload: ProductionStartPayload,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        try:
            job = production.regenerate_page(
                project_id,
                page_id,
                payload.recipe_id,
                quality=payload.quality,
            )
            background_tasks.add_task(production.process_project, project_id)
            return job_to_dict(job) or {}
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/candidates/{candidate_id}/review")
    def review_candidate(candidate_id: str, payload: ReviewPayload) -> dict[str, Any]:
        try:
            decision = production.review_candidate(
                candidate_id, payload.decision, payload.override_reason, payload.reviewer
            )
            return decision_to_dict(decision)
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/candidates/{candidate_id}/edit", status_code=202)
    def edit_candidate(
        candidate_id: str,
        payload: CandidateEditPayload,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        try:
            job = production.request_candidate_edit(
                candidate_id, payload.instruction, quality=payload.quality
            )
            background_tasks.add_task(production.process_project, job.project_id)
            return job_to_dict(job) or {}
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/candidates/{candidate_id}/files/{kind}")
    def get_candidate_file(candidate_id: str, kind: str) -> FileResponse:
        try:
            path = production.candidate_file(candidate_id, kind)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type="image/png")

    @app.post("/api/projects/{project_id}/export", status_code=201)
    def export_project(project_id: str) -> dict[str, str]:
        try:
            path = production.export_project(project_id)
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"file_name": path.name, "download_url": f"/api/exports/{path.name}"}

    @app.post("/api/projects/{project_id}/stitch", status_code=201)
    def stitch_project(project_id: str, payload: StitchPayload) -> dict[str, str]:
        try:
            path = production.stitch_project(
                project_id,
                payload.candidate_ids,
                direction=payload.direction,
                gap=payload.gap,
                background_color=payload.background_color,
                alignment=payload.alignment,
            )
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"file_name": path.name, "download_url": f"/api/exports/{path.name}"}

    @app.post("/api/projects/{project_id}/recipe-candidate", status_code=201)
    def create_recipe_from_project(project_id: str, payload: RecipeCandidatePayload) -> dict[str, Any]:
        try:
            return recipe_to_dict(production.create_recipe_from_project(project_id, payload.name))
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/exports/{file_name}")
    def download_export(file_name: str) -> FileResponse:
        try:
            path = exporter.resolve(file_name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="导出文件不存在") from exc
        media_type = "image/png" if path.suffix.lower() == ".png" else "application/zip"
        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.get("/api/jobs")
    def list_jobs(project_id: str | None = None) -> list[dict[str, Any]]:
        return [job_to_dict(job) for job in production.list_jobs(project_id)]

    @app.post("/api/jobs/recover", status_code=202)
    def recover_jobs(background_tasks: BackgroundTasks) -> dict[str, Any]:
        queued_projects = sorted({job.project_id for job in production.list_jobs() if job.status.value == "queued"})
        background_tasks.add_task(production.recover_pending)
        return {"queued_projects": queued_projects}

    @app.post("/api/batches", status_code=201)
    def create_batch(payload: BatchCreatePayload) -> dict[str, Any]:
        try:
            batch = platform.create_batch(
                payload.name,
                [
                    BatchSkuInput(
                        profile=item.profile.to_domain(),
                        override_config=item.override_config,
                    )
                    for item in payload.skus
                ],
                payload.common_config,
            )
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return batch_to_dict(batch)

    @app.get("/api/batches")
    def list_batches() -> list[dict[str, Any]]:
        return [batch_to_dict(batch) for batch in platform.list_batches()]

    @app.get("/api/batches-import-template")
    def download_batch_import_template() -> Response:
        content = (
            "\ufeffSKU,商品名称,品类,型号,卖点,参数,品牌要求,输出要求\n"
            "X11,COLMO X11洗衣机,洗衣机,CGU12W-X11,低温柔洗|智能投放,容量=12kg|洗净比=1.1,,电商详情页\n"
        )
        return Response(
            content=content.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="sku_import_template.csv"'},
        )

    @app.post("/api/batches-import", status_code=201)
    async def import_batch(
        request: Request,
        name: str = Query(min_length=1),
        file_name: str = Query(min_length=1),
        default_category: str = "",
    ) -> dict[str, Any]:
        try:
            profiles = imports.parse(file_name, await request.body(), default_category)
            batch = platform.create_batch(
                name,
                [BatchSkuInput(profile=profile) for profile in profiles],
                {"recipe_id": "commerce-detail-v1", "source": "file_import"},
            )
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return batch_to_dict(batch)

    @app.get("/api/batches/{batch_id}/production")
    def get_batch_production(batch_id: str) -> dict[str, Any]:
        try:
            return batch_snapshot_to_dict(production.batch_snapshot(batch_id))
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/batches/{batch_id}/production/start", status_code=202)
    def start_batch_production(
        batch_id: str,
        payload: ProductionStartPayload,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        try:
            snapshot = production.start_batch(
                batch_id,
                payload.recipe_id,
                failed_only=False,
                quality=payload.quality,
            )
            background_tasks.add_task(production.process_batch, batch_id)
            return batch_snapshot_to_dict(snapshot)
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/batches/{batch_id}/production/retry", status_code=202)
    def retry_batch_production(
        batch_id: str,
        payload: ProductionStartPayload,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        try:
            snapshot = production.start_batch(
                batch_id,
                payload.recipe_id,
                failed_only=True,
                quality=payload.quality,
            )
            background_tasks.add_task(production.process_batch, batch_id)
            return batch_snapshot_to_dict(snapshot)
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/batches/{batch_id}/pause")
    def pause_batch(batch_id: str) -> dict[str, Any]:
        try:
            return batch_snapshot_to_dict(production.pause_batch(batch_id))
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/batches/{batch_id}/resume", status_code=202)
    def resume_batch(batch_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
        try:
            snapshot = production.resume_batch(batch_id)
            background_tasks.add_task(production.process_batch, batch_id)
            return batch_snapshot_to_dict(snapshot)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/batches/{batch_id}/export", status_code=201)
    def export_batch(batch_id: str) -> dict[str, str]:
        try:
            path = production.export_batch(batch_id)
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"file_name": path.name, "download_url": f"/api/exports/{path.name}"}

    @app.get("/api/batches/{batch_id}")
    def get_batch(batch_id: str) -> dict[str, Any]:
        try:
            return batch_to_dict(platform.get_batch(batch_id))
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/batches/{batch_id}/items/{item_id}")
    def update_batch_item(
        batch_id: str,
        item_id: str,
        payload: BatchItemStatusPayload,
    ) -> dict[str, Any]:
        try:
            batch = platform.set_batch_item_status(batch_id, item_id, payload.status, payload.error)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return batch_to_dict(batch)

    return app


def project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "status": project.status.value,
        "profile": project.profile.to_dict(),
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def asset_to_dict(asset: Asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "project_id": asset.project_id,
        "usage": asset.usage.value,
        "file_name": asset.file_name,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "source": asset.source,
        "authorization_status": asset.authorization_status,
        "content_url": f"/api/assets/{asset.id}/content",
        "created_at": asset.created_at.isoformat(),
    }


def plan_to_dict(plan: PagePlan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "project_id": plan.project_id,
        "version": plan.version,
        "layout_library_id": plan.layout_library_id,
        "confirmed": plan.confirmed,
        "items": [
            {
                "id": item.id,
                "order": item.order,
                "page_type": item.page_type.value,
                "title": item.title,
                "body": item.body,
                "visual_goal": item.visual_goal,
                "template_id": item.template_id,
                "heading_level": item.heading_level,
                "status": item.status.value,
            }
            for item in plan.items
        ],
        "created_at": plan.created_at.isoformat(),
        "updated_at": plan.updated_at.isoformat(),
    }


def planning_run_to_dict(run: Any) -> dict[str, Any]:
    input_snapshot = dict(run.input_snapshot)
    input_snapshot["assets"] = [
        {key: value for key, value in asset.items() if key != "storage_path"}
        for asset in input_snapshot.get("assets", [])
    ]
    return {
        "id": run.id,
        "project_id": run.project_id,
        "status": run.status.value,
        "layout_library_id": run.layout_library_id,
        "base_plan_version": run.base_plan_version,
        "input_snapshot": input_snapshot,
        "suggestion": run.suggestion,
        "error": run.error,
        "degraded": run.degraded,
        "applied_fields": run.applied_fields,
        "applied_plan_version": run.applied_plan_version,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def batch_to_dict(batch: Batch) -> dict[str, Any]:
    return {
        "id": batch.id,
        "name": batch.name,
        "status": batch.status.value,
        "common_config": batch.common_config,
        "items": [
            {
                "id": item.id,
                "batch_id": item.batch_id,
                "project_id": item.project_id,
                "sku": item.sku,
                "status": item.status.value,
                "override_config": item.override_config,
                "error": item.error,
            }
            for item in batch.items
        ],
        "progress": batch.progress,
        "created_at": batch.created_at.isoformat(),
        "updated_at": batch.updated_at.isoformat(),
    }


def prompt_to_dict(prompt: PromptVersion) -> dict[str, Any]:
    return {
        "id": prompt.id,
        "prompt_asset_id": prompt.prompt_asset_id,
        "name": prompt.name,
        "version": prompt.version,
        "body": prompt.body,
        "variables": list(prompt.variables),
        "status": prompt.status.value,
        "change_note": prompt.change_note,
        "created_at": prompt.created_at.isoformat(),
    }


def recipe_to_dict(recipe: Recipe) -> dict[str, Any]:
    return {
        "id": recipe.id,
        "name": recipe.name,
        "status": recipe.status.value,
        "prompt_version_id": recipe.prompt_version_id,
        "model": recipe.model,
        "model_params": recipe.model_params,
        "template_ids": list(recipe.template_ids),
        "page_types": ["hero", "selling_point", "function", "scene", "parameters"],
        "qa_policy": recipe.qa_policy,
        "candidate_count": recipe.candidate_count,
        "version": 1,
        "created_at": recipe.created_at.isoformat(),
        "updated_at": recipe.updated_at.isoformat(),
    }


def job_to_dict(job: GenerationJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    return {
        "id": job.id,
        "project_id": job.project_id,
        "page_id": job.page_id,
        "recipe_id": job.recipe_id,
        "status": job.status.value,
        "attempt": job.attempt,
        "max_attempts": job.max_attempts,
        "error": job.error,
        "trace": job.trace,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def candidate_to_dict(candidate: Candidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "job_id": candidate.job_id,
        "project_id": candidate.project_id,
        "page_id": candidate.page_id,
        "candidate_index": candidate.candidate_index,
        "score": candidate.score,
        "rank": candidate.rank,
        "status": candidate.status.value,
        "prompt": candidate.prompt,
        "metadata": candidate.metadata,
        "base_url": f"/api/candidates/{candidate.id}/files/base",
        "text_layer_url": f"/api/candidates/{candidate.id}/files/text",
        "composed_url": f"/api/candidates/{candidate.id}/files/composed",
        "background_url": (
            f"/api/candidates/{candidate.id}/files/background"
            if (candidate.metadata.get("generator") or {}).get("background_file") else ""
        ),
        "product_layer_url": (
            f"/api/candidates/{candidate.id}/files/product_layer"
            if (candidate.metadata.get("generator") or {}).get("product_layer_file") else ""
        ),
        "created_at": candidate.created_at.isoformat(),
    }


def qa_to_dict(qa: QAResult | None) -> dict[str, Any] | None:
    if qa is None:
        return None
    return {
        "id": qa.id,
        "candidate_id": qa.candidate_id,
        "status": qa.status.value,
        "score": qa.score,
        "issues": list(qa.issues),
        "evidence": qa.evidence,
        "suggested_fix": qa.suggested_fix,
        "repair_applied": qa.repair_applied,
        "created_at": qa.created_at.isoformat(),
    }


def decision_to_dict(decision: ReviewDecision | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    return {
        "id": decision.id,
        "project_id": decision.project_id,
        "page_id": decision.page_id,
        "candidate_id": decision.candidate_id,
        "decision": decision.decision.value,
        "override_reason": decision.override_reason,
        "reviewer": decision.reviewer,
        "created_at": decision.created_at.isoformat(),
    }


def production_snapshot_to_dict(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "project": project_to_dict(snapshot["project"]),
        "plan": plan_to_dict(snapshot["plan"]),
        "ready_for_export": snapshot["ready_for_export"],
        "pages": [
            {
                "page": {
                    "id": row["page"].id,
                    "order": row["page"].order,
                    "page_type": row["page"].page_type.value,
                    "title": row["page"].title,
                    "body": row["page"].body,
                    "visual_goal": row["page"].visual_goal,
                    "template_id": row["page"].template_id,
                    "heading_level": row["page"].heading_level,
                    "status": row["page"].status.value,
                },
                "job": job_to_dict(row["job"]),
                "candidates": [
                    {**candidate_to_dict(candidate), "qa": qa_to_dict(row["qa_results"].get(candidate.id))}
                    for candidate in row["candidates"]
                ],
                "history": [
                    {**candidate_to_dict(candidate), "qa": qa_to_dict(row["history_qa_results"].get(candidate.id))}
                    for candidate in row["history"]
                ],
                "decision": decision_to_dict(row["decision"]),
            }
            for row in snapshot["pages"]
        ],
    }


def batch_snapshot_to_dict(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "batch": batch_to_dict(snapshot["batch"]),
        "items": [
            {"item": batch_to_dict(snapshot["batch"])["items"][index], "project": project_to_dict(row["project"])}
            for index, row in enumerate(snapshot["items"])
        ],
    }


app = create_app()
