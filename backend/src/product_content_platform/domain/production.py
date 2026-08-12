from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from .models import utc_now


class PublishStatus(StrEnum):
    DRAFT = "draft"
    TESTING = "testing"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CandidateStatus(StrEnum):
    GENERATED = "generated"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class QAStatus(StrEnum):
    PASS = "pass"
    REVIEW = "review"
    FAIL = "fail"


class ReviewDecisionType(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PromptVersion:
    id: str
    prompt_asset_id: str
    name: str
    version: int
    body: str
    variables: tuple[str, ...]
    status: PublishStatus
    change_note: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class Recipe:
    id: str
    name: str
    status: PublishStatus
    prompt_version_id: str
    model: str
    model_params: dict[str, Any]
    template_ids: tuple[str, ...]
    qa_policy: str
    candidate_count: int = 2
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class GenerationJob:
    id: str
    project_id: str
    page_id: str
    recipe_id: str
    status: JobStatus
    attempt: int = 0
    max_attempts: int = 2
    error: str = ""
    trace: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    job_id: str
    project_id: str
    page_id: str
    candidate_index: int
    base_path: str
    text_layer_path: str
    composed_path: str
    prompt: str
    score: int
    rank: int
    status: CandidateStatus
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class QAResult:
    id: str
    candidate_id: str
    status: QAStatus
    score: int
    issues: tuple[dict[str, Any], ...]
    evidence: dict[str, Any]
    suggested_fix: str = ""
    repair_applied: bool = False
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    id: str
    project_id: str
    page_id: str
    candidate_id: str
    decision: ReviewDecisionType
    override_reason: str = ""
    qa_disposition: str = "qa_completed"
    reviewer: str = "local-user"
    created_at: datetime = field(default_factory=utc_now)
