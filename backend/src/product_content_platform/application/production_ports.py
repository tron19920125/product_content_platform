from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from product_content_platform.domain import (
    Candidate,
    GenerationJob,
    PageItem,
    ProductProfile,
    Project,
    PromptVersion,
    QAResult,
    Recipe,
    ReviewDecision,
    TextDocument,
)


@dataclass(frozen=True, slots=True)
class ProducedCandidate:
    candidate_index: int
    base_path: str
    text_layer_path: str
    composed_path: str
    prompt: str
    score: int
    rank: int
    qa_status: str
    issues: tuple[dict[str, Any], ...]
    evidence: dict[str, Any]
    suggested_fix: str = ""
    repair_applied: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseImageGenerator(Protocol):
    def generate(
        self,
        *,
        prompt: str,
        profile: ProductProfile,
        reference_paths: list[Path],
        output_path: Path,
        variant: int,
        size: str,
        quality: str,
        layout: dict[str, Any],
        reference_strategy: str,
    ) -> dict[str, Any]: ...

    def edit(
        self,
        *,
        prompt: str,
        profile: ProductProfile,
        source_base_path: Path,
        reference_paths: list[Path],
        output_path: Path,
        size: str,
        quality: str,
        layout: dict[str, Any],
    ) -> dict[str, Any]: ...


class PageProductionEngine(Protocol):
    def execute(
        self,
        *,
        project: Project,
        page: PageItem,
        recipe: Recipe,
        prompt_version: PromptVersion,
        reference_paths: list[Path],
        progress: Callable[[str, int, dict[str, Any]], None] | None = None,
    ) -> list[ProducedCandidate]: ...

    def recompose(
        self,
        *,
        project: Project,
        page: PageItem,
        recipe: Recipe,
        prompt_version: PromptVersion,
        source_candidate: Candidate,
        reference_paths: list[Path],
        typography: dict[str, Any] | None = None,
    ) -> ProducedCandidate: ...

    def suggest_text_document(
        self,
        *,
        candidate: Candidate,
        page: PageItem,
        instruction: str = "",
        current: TextDocument | None = None,
    ) -> TextDocument: ...

    def recompose_document(
        self,
        *,
        project: Project,
        page: PageItem,
        recipe: Recipe,
        prompt_version: PromptVersion,
        source_candidate: Candidate,
        text_document: TextDocument,
        reference_paths: list[Path],
        run_qa: bool = False,
    ) -> ProducedCandidate: ...

    def inspect_candidate(
        self,
        *,
        project: Project,
        page: PageItem,
        recipe: Recipe,
        prompt_version: PromptVersion,
        candidate: Candidate,
        reference_paths: list[Path],
    ) -> ProducedCandidate: ...

    def edit_candidate(
        self,
        *,
        project: Project,
        page: PageItem,
        recipe: Recipe,
        prompt_version: PromptVersion,
        source_candidate: Candidate,
        instruction: str,
        quality: str,
        reference_paths: list[Path],
        progress: Callable[[str, int, dict[str, Any]], None] | None = None,
    ) -> ProducedCandidate: ...

    def resolve(self, relative_path: str) -> Path: ...


class ArchiveExporter(Protocol):
    def create(
        self,
        archive_name: str,
        files: dict[str, Path],
        documents: dict[str, Any],
    ) -> Path: ...

    def resolve(self, file_name: str) -> Path: ...

    def stitch(
        self,
        export_name: str,
        images: list[Path],
        *,
        direction: str,
        gap: int,
        background_color: str,
        alignment: str,
    ) -> Path: ...


class ProductionRepository(Protocol):
    def ensure_seed_data(self, prompt: PromptVersion, recipe: Recipe) -> None: ...
    def save_prompt_version(self, prompt: PromptVersion) -> None: ...
    def update_prompt_status(self, prompt_id: str, status: Any) -> None: ...
    def get_prompt_version(self, prompt_id: str) -> PromptVersion | None: ...
    def list_prompt_versions(self) -> list[PromptVersion]: ...
    def save_recipe(self, recipe: Recipe) -> None: ...
    def get_recipe(self, recipe_id: str) -> Recipe | None: ...
    def list_recipes(self) -> list[Recipe]: ...
    def create_jobs(self, jobs: list[GenerationJob]) -> None: ...
    def get_job(self, job_id: str) -> GenerationJob | None: ...
    def list_jobs(self, project_id: str | None = None) -> list[GenerationJob]: ...
    def update_job(self, job: GenerationJob) -> None: ...
    def save_job_results(self, job: GenerationJob, candidates: list[Candidate], qa_results: list[QAResult]) -> None: ...
    def get_candidate(self, candidate_id: str) -> Candidate | None: ...
    def list_candidates(self, project_id: str, page_id: str | None = None) -> list[Candidate]: ...
    def get_qa_result(self, candidate_id: str) -> QAResult | None: ...
    def save_qa_result(self, result: QAResult) -> None: ...
    def update_candidate_status(self, candidate_id: str, status: Any) -> None: ...
    def save_text_document(self, document: TextDocument) -> None: ...
    def get_text_document(self, candidate_id: str, version: int | None = None) -> TextDocument | None: ...
    def list_text_documents(self, candidate_id: str) -> list[TextDocument]: ...
    def save_decision(self, decision: ReviewDecision) -> None: ...
    def list_decisions(self, project_id: str) -> list[ReviewDecision]: ...
