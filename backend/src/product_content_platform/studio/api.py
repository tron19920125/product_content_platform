from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import Field

from .catalog import AssetUsage, DraftContent, StrictModel, Tool, catalog
from .settings import StudioSettings
from .workspace import RevisionConflict, StudioWorkspace
from .creations import Creations
from .library import Library, LibraryKind
from .quality import Review
from .quality_tasks import QualityChecks
from .demo import DemoPack
from .planning import CodexPlanner, Planner, apply_plan


class CreateDraft(StrictModel):
    tool: Tool = Field(strict=False)


class SaveDraft(StrictModel):
    expected_revision: int = Field(ge=1)
    content: DraftContent


class Generate(StrictModel):
    submit_key: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=1)
    mode: Literal["demo", "codex"] = "codex"
    page_ids: list[str] | None = None
    source_version_id: str | None = None
    instruction: str = Field(default="", max_length=8000)


class CompleteJob(StrictModel):
    asset_id: str
    review: Review
    provenance: dict = Field(default_factory=dict)


class SelectVersion(StrictModel):
    page_id: str
    version_id: str


class EditDraft(StrictModel):
    expected_revision: int = Field(ge=0)
    layers: list[dict] = Field(max_length=100)


class ApplyEdit(StrictModel):
    expected_revision: int = Field(ge=1)
    rendered_asset_id: str


class SaveLibrary(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    kind: LibraryKind
    payload: dict = Field(default_factory=dict)
    asset_ids: list[str] = Field(default_factory=list, max_length=300)


class LibraryAction(StrictModel):
    action: Literal["rename", "trash", "restore", "purge"]
    name: str = Field(default="", max_length=200)


class PlanDraft(StrictModel):
    expected_revision: int = Field(ge=1)


class DraftAction(StrictModel):
    action: Literal["trash", "restore", "purge"]


class RestorePlan(StrictModel):
    expected_revision: int = Field(ge=1)


class ReviewFailure(StrictModel):
    message: str = Field(min_length=1, max_length=2000)


def create_app(settings: StudioSettings | None = None, planner: Planner | None = None) -> FastAPI:
    configuration = settings or StudioSettings.from_environment()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.workspace = StudioWorkspace(configuration)
        app.state.creations = Creations(app.state.workspace)
        app.state.creations.recover()
        app.state.creations.clean_expired_drafts()
        app.state.quality = QualityChecks(app.state.workspace, app.state.creations)
        app.state.quality.recover()
        app.state.library = Library(app.state.workspace)
        app.state.library.clean_expired()
        app.state.demo = DemoPack(app.state.workspace, app.state.creations)
        app.state.planner = planner or CodexPlanner(configuration.data_root)
        yield

    app = FastAPI(title="Product Studio · Refactor", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5174", "http://localhost:5174"],
        allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type"],
    )

    @app.exception_handler(ValueError)
    async def invalid_input(_: Request, error: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(KeyError)
    async def missing_record(_: Request, error: KeyError):
        return JSONResponse(status_code=404, content={"detail": str(error.args[0])})

    @app.exception_handler(RevisionConflict)
    async def stale_draft(_: Request, error: RevisionConflict):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(RuntimeError)
    async def unavailable_dependency(_: Request, error: RuntimeError):
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok", "workspace": "studio", "stage": "local-studio-beta",
            "generation_available": False, "generation_submission_available": True,
            "demo_available": True, "planning_available": request_planner_available(app),
            "azure_configured": False,
        }

    @app.get("/api/studio/catalog")
    def get_catalog() -> dict:
        return catalog(reference_limit=configuration.max_references, max_upload_bytes=configuration.max_upload_bytes)

    @app.post("/api/studio/drafts", status_code=201)
    def create_draft(payload: CreateDraft, request: Request) -> dict:
        return request.app.state.workspace.create_draft(payload.tool)

    @app.get("/api/studio/drafts")
    def list_drafts(request: Request, tool: Tool | None = None, trash: bool = False) -> list[dict]:
        return request.app.state.workspace.list_drafts(tool, trash=trash)

    @app.get("/api/studio/drafts/{identifier}")
    def get_draft(identifier: str, request: Request) -> dict:
        return request.app.state.workspace.get_draft(identifier)

    @app.get("/api/studio/history")
    def history(request: Request, trash: bool = False) -> list[dict]:
        return request.app.state.creations.history(trash=trash)

    @app.put("/api/studio/drafts/{identifier}")
    def save_draft(identifier: str, payload: SaveDraft, request: Request) -> dict:
        return request.app.state.workspace.save_draft(
            identifier, payload.content, expected_revision=payload.expected_revision,
        )

    @app.post("/api/studio/drafts/{identifier}/lifecycle")
    def change_draft_lifecycle(identifier: str, payload: DraftAction, request: Request) -> dict:
        return request.app.state.creations.change_draft(identifier, action=payload.action)

    @app.post("/api/studio/drafts/{identifier}/plan")
    def plan_draft(identifier: str, payload: PlanDraft, request: Request) -> dict:
        draft = request.app.state.workspace.get_draft(identifier)
        if draft["revision"] != payload.expected_revision:
            raise RevisionConflict("输入已变化，请保存后重新规划")
        content = DraftContent.model_validate(draft["content"])
        if content.tool != Tool.A_PLUS:
            raise ValueError("只有 A+ 详情图需要生成模块方案")
        result = request.app.state.planner.plan(content)
        request.app.state.workspace.record_plan(identifier, content, label="重新规划前")
        saved = request.app.state.workspace.save_draft(
            identifier, apply_plan(content, result), expected_revision=payload.expected_revision,
        )
        request.app.state.workspace.record_plan(
            identifier, DraftContent.model_validate(saved["content"]), label="Codex 模块方案",
        )
        return saved

    @app.get("/api/studio/drafts/{identifier}/plans")
    def list_plan_versions(identifier: str, request: Request) -> list[dict]:
        return request.app.state.workspace.list_plans(identifier)

    @app.post("/api/studio/drafts/{identifier}/plans/{plan_id}/restore")
    def restore_plan_version(identifier: str, plan_id: str, payload: RestorePlan, request: Request) -> dict:
        return request.app.state.workspace.restore_plan(
            identifier, plan_id, expected_revision=payload.expected_revision,
        )

    @app.post("/api/studio/assets", status_code=201)
    async def upload_image(
        request: Request, usage: AssetUsage,
        filename: str = Query(min_length=1, max_length=240),
    ) -> dict:
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > configuration.max_upload_bytes:
                raise HTTPException(status_code=413, detail="图片超过上传大小限制")
            content.extend(chunk)
        # Decoding and disk I/O must not block the server's async event loop.
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(request.app.state.workspace.upload_image, filename, usage, bytes(content))

    @app.get("/api/studio/assets/{identifier}")
    def get_asset(identifier: str, request: Request) -> dict:
        return request.app.state.workspace.get_asset(identifier)

    @app.get("/api/studio/assets/{identifier}/{kind}")
    def asset_content(identifier: str, kind: Literal["preview", "source"], request: Request) -> FileResponse:
        path, media_type = request.app.state.workspace.asset_file(identifier, preview=kind == "preview")
        return FileResponse(path, media_type=media_type, headers={"X-Content-Type-Options": "nosniff"})

    @app.post("/api/studio/drafts/{identifier}/generate", status_code=202)
    def generate(identifier: str, payload: Generate, request: Request, background: BackgroundTasks) -> dict:
        operation = request.app.state.creations.submit(identifier, **payload.model_dump())
        if payload.mode == "demo":
            background.add_task(request.app.state.demo.replay, operation["id"])
        return operation

    @app.get("/api/studio/demo")
    def demo_manifest(request: Request):
        return request.app.state.demo.manifest()

    @app.post("/api/studio/demo/drafts", status_code=201)
    def demo_draft(payload: CreateDraft, request: Request):
        return request.app.state.demo.create_draft(payload.tool)

    @app.get("/api/studio/drafts/{identifier}/results")
    def results(identifier: str, request: Request) -> dict:
        return request.app.state.creations.snapshot(identifier)

    @app.post("/api/studio/drafts/{identifier}/selection")
    def selection(identifier: str, payload: SelectVersion, request: Request) -> dict:
        return request.app.state.creations.select(identifier, payload.page_id, payload.version_id)

    @app.post("/api/studio/operations/{identifier}/stop")
    def stop(identifier: str, request: Request) -> dict:
        return request.app.state.creations.stop(identifier)

    @app.post("/api/studio/jobs/{identifier}/retry")
    def retry(identifier: str, request: Request) -> dict:
        return request.app.state.creations.retry(identifier)

    @app.post("/api/studio/execution/next")
    def next_job(request: Request, operation_id: str | None = None):
        return request.app.state.creations.claim(operation_id)

    @app.post("/api/studio/execution/{identifier}/complete")
    def complete(identifier: str, payload: CompleteJob, request: Request) -> dict:
        version = request.app.state.creations.complete(identifier, **payload.model_dump(exclude={"review"}), review=payload.review)
        if payload.review.status != "completed":
            request.app.state.quality.request(version["id"])
        return version

    @app.post("/api/studio/versions/{identifier}/recheck", status_code=202)
    def recheck_version(identifier: str, request: Request) -> dict:
        return request.app.state.quality.request(identifier)

    @app.get("/api/studio/versions/{identifier}/review-task")
    def review_task(identifier: str, request: Request) -> dict | None:
        return request.app.state.quality.status_for(identifier)

    @app.post("/api/studio/execution/next-review")
    def next_review(request: Request) -> dict | None:
        return request.app.state.quality.claim()

    @app.post("/api/studio/reviews/{identifier}/complete")
    def complete_review(identifier: str, payload: Review, request: Request) -> dict:
        return request.app.state.quality.complete(identifier, payload)

    @app.post("/api/studio/reviews/{identifier}/fail")
    def fail_review(identifier: str, payload: ReviewFailure, request: Request) -> dict:
        return request.app.state.quality.fail(identifier, message=payload.message)

    @app.get("/api/studio/versions/{identifier}/edit")
    def get_edit(identifier: str, request: Request) -> dict:
        return request.app.state.creations.get_edit(identifier)

    @app.put("/api/studio/versions/{identifier}/edit")
    def save_edit(identifier: str, payload: EditDraft, request: Request) -> dict:
        return request.app.state.creations.save_edit(identifier, **payload.model_dump())

    @app.post("/api/studio/versions/{identifier}/apply")
    def apply_edit(identifier: str, payload: ApplyEdit, request: Request) -> dict:
        return request.app.state.creations.apply_edit(identifier, **payload.model_dump())

    @app.delete("/api/studio/versions/{identifier}/edit")
    def discard_edit(identifier: str, request: Request) -> dict:
        request.app.state.creations.discard_edit(identifier)
        return {"discarded": True}

    @app.get("/api/studio/library")
    def library(request: Request, trash: bool = False, kind: str = "", query: str = ""):
        return request.app.state.library.list(trash=trash, kind=kind, query=query)

    @app.post("/api/studio/library", status_code=201)
    def save_library(payload: SaveLibrary, request: Request):
        return request.app.state.library.save(**payload.model_dump())

    @app.post("/api/studio/library/{identifier}")
    def change_library(identifier: str, payload: LibraryAction, request: Request):
        return request.app.state.library.change(identifier, **payload.model_dump())

    @app.post("/api/studio/library/{identifier}/continue", status_code=201)
    def continue_library_work(identifier: str, request: Request):
        entry = request.app.state.library.get(identifier)
        if entry["deleted_at"]:
            raise ValueError("请先从回收站恢复作品，再继续编辑")
        return request.app.state.creations.restore_work(entry)

    frontend_dist = Path(__file__).resolve().parents[4] / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="studio-ui")
    return app


def request_planner_available(app: FastAPI) -> bool:
    planner = getattr(app.state, "planner", None)
    return bool(getattr(planner, "available", True))


# Importing this module has no filesystem or model-call side effects.
app = create_app()
