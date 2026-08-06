from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from product_content_platform.domain import (
    Candidate,
    CandidateStatus,
    GenerationJob,
    JobStatus,
    PromptVersion,
    PublishStatus,
    QAResult,
    QAStatus,
    Recipe,
    ReviewDecision,
    ReviewDecisionType,
)


class SQLiteProductionRepository:
    """Persistent adapter for recipe, generation, QA and human-review records."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def ensure_seed_data(self, prompt: PromptVersion, recipe: Recipe) -> None:
        if self.get_prompt_version(prompt.id) is None:
            self.save_prompt_version(prompt)
        if self.get_recipe(recipe.id) is None:
            self.save_recipe(recipe)

    def save_prompt_version(self, prompt: PromptVersion) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO prompt_versions
                    (id, prompt_asset_id, name, version, body, variables, status, change_note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prompt.id, prompt.prompt_asset_id, prompt.name, prompt.version, prompt.body,
                    json.dumps(prompt.variables, ensure_ascii=False), prompt.status.value,
                    prompt.change_note, prompt.created_at.isoformat(),
                ),
            )

    def get_prompt_version(self, prompt_id: str) -> PromptVersion | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM prompt_versions WHERE id = ?", (prompt_id,)).fetchone()
        return self._prompt_from_row(row) if row else None

    def update_prompt_status(self, prompt_id: str, status: PublishStatus) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE prompt_versions SET status = ? WHERE id = ?", (status.value, prompt_id)
            )
            if cursor.rowcount == 0:
                raise LookupError(prompt_id)

    def list_prompt_versions(self) -> list[PromptVersion]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM prompt_versions ORDER BY prompt_asset_id, version DESC"
            ).fetchall()
        return [self._prompt_from_row(row) for row in rows]

    def save_recipe(self, recipe: Recipe) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO recipes
                    (id, name, status, prompt_version_id, model, model_params, template_ids,
                     qa_policy, candidate_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, status=excluded.status,
                    prompt_version_id=excluded.prompt_version_id, model=excluded.model,
                    model_params=excluded.model_params, template_ids=excluded.template_ids,
                    qa_policy=excluded.qa_policy, candidate_count=excluded.candidate_count,
                    updated_at=excluded.updated_at
                """,
                (
                    recipe.id, recipe.name, recipe.status.value, recipe.prompt_version_id,
                    recipe.model, json.dumps(recipe.model_params, ensure_ascii=False),
                    json.dumps(recipe.template_ids, ensure_ascii=False), recipe.qa_policy,
                    recipe.candidate_count, recipe.created_at.isoformat(), recipe.updated_at.isoformat(),
                ),
            )

    def get_recipe(self, recipe_id: str) -> Recipe | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        return self._recipe_from_row(row) if row else None

    def list_recipes(self) -> list[Recipe]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM recipes ORDER BY updated_at DESC").fetchall()
        return [self._recipe_from_row(row) for row in rows]

    def create_jobs(self, jobs: list[GenerationJob]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO generation_jobs
                    (id, project_id, page_id, recipe_id, status, attempt, max_attempts,
                     error, trace, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._job_values(job) for job in jobs],
            )

    def get_job(self, job_id: str) -> GenerationJob | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_from_row(row) if row else None

    def list_jobs(self, project_id: str | None = None) -> list[GenerationJob]:
        query = "SELECT * FROM generation_jobs"
        params: tuple[str, ...] = ()
        if project_id:
            query += " WHERE project_id = ?"
            params = (project_id,)
        query += " ORDER BY created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._job_from_row(row) for row in rows]

    def update_job(self, job: GenerationJob) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE generation_jobs
                SET status=?, attempt=?, max_attempts=?, error=?, trace=?, updated_at=?
                WHERE id=?
                """,
                (
                    job.status.value, job.attempt, job.max_attempts, job.error,
                    json.dumps(job.trace, ensure_ascii=False), job.updated_at.isoformat(), job.id,
                ),
            )

    def save_job_results(
        self,
        job: GenerationJob,
        candidates: list[Candidate],
        qa_results: list[QAResult],
    ) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO candidates
                    (id, job_id, project_id, page_id, candidate_index, base_path,
                     text_layer_path, composed_path, prompt, score, rank, status, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id, item.job_id, item.project_id, item.page_id, item.candidate_index,
                        item.base_path, item.text_layer_path, item.composed_path, item.prompt,
                        item.score, item.rank, item.status.value,
                        json.dumps(item.metadata, ensure_ascii=False), item.created_at.isoformat(),
                    )
                    for item in candidates
                ],
            )
            connection.executemany(
                """
                INSERT INTO qa_results
                    (id, candidate_id, status, score, issues, evidence, suggested_fix,
                     repair_applied, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id, item.candidate_id, item.status.value, item.score,
                        json.dumps(item.issues, ensure_ascii=False),
                        json.dumps(item.evidence, ensure_ascii=False), item.suggested_fix,
                        int(item.repair_applied), item.created_at.isoformat(),
                    )
                    for item in qa_results
                ],
            )
            connection.execute(
                """
                UPDATE generation_jobs
                SET status=?, attempt=?, error=?, trace=?, updated_at=? WHERE id=?
                """,
                (
                    job.status.value, job.attempt, job.error,
                    json.dumps(job.trace, ensure_ascii=False), job.updated_at.isoformat(), job.id,
                ),
            )

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
        return self._candidate_from_row(row) if row else None

    def list_candidates(self, project_id: str, page_id: str | None = None) -> list[Candidate]:
        query = "SELECT * FROM candidates WHERE project_id = ?"
        params: tuple[str, ...] = (project_id,)
        if page_id:
            query += " AND page_id = ?"
            params = (project_id, page_id)
        query += " ORDER BY created_at DESC, rank ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._candidate_from_row(row) for row in rows]

    def get_qa_result(self, candidate_id: str) -> QAResult | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM qa_results WHERE candidate_id = ?", (candidate_id,)).fetchone()
        return self._qa_from_row(row) if row else None

    def save_decision(self, decision: ReviewDecision) -> None:
        with self._connect() as connection:
            if decision.decision is ReviewDecisionType.APPROVED:
                connection.execute(
                    "UPDATE candidates SET status = ? WHERE project_id = ? AND page_id = ?",
                    (CandidateStatus.GENERATED.value, decision.project_id, decision.page_id),
                )
            connection.execute(
                """
                INSERT INTO review_decisions
                    (id, project_id, page_id, candidate_id, decision, override_reason, reviewer, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.id, decision.project_id, decision.page_id, decision.candidate_id,
                    decision.decision.value, decision.override_reason, decision.reviewer,
                    decision.created_at.isoformat(),
                ),
            )
            candidate_status = (
                CandidateStatus.APPROVED if decision.decision is ReviewDecisionType.APPROVED
                else CandidateStatus.REJECTED
            )
            connection.execute(
                "UPDATE candidates SET status = ? WHERE id = ?",
                (candidate_status.value, decision.candidate_id),
            )

    def list_decisions(self, project_id: str) -> list[ReviewDecision]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM review_decisions WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [self._decision_from_row(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS prompt_versions (
                    id TEXT PRIMARY KEY,
                    prompt_asset_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    body TEXT NOT NULL,
                    variables TEXT NOT NULL,
                    status TEXT NOT NULL,
                    change_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(prompt_asset_id, version)
                );

                CREATE TABLE IF NOT EXISTS recipes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    prompt_version_id TEXT NOT NULL REFERENCES prompt_versions(id),
                    model TEXT NOT NULL,
                    model_params TEXT NOT NULL,
                    template_ids TEXT NOT NULL,
                    qa_policy TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS generation_jobs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    page_id TEXT NOT NULL,
                    recipe_id TEXT NOT NULL REFERENCES recipes(id),
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    trace TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_generation_jobs_project ON generation_jobs(project_id);

                CREATE TABLE IF NOT EXISTS candidates (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    page_id TEXT NOT NULL,
                    candidate_index INTEGER NOT NULL,
                    base_path TEXT NOT NULL,
                    text_layer_path TEXT NOT NULL,
                    composed_path TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    rank INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_candidates_project_page ON candidates(project_id, page_id);

                CREATE TABLE IF NOT EXISTS qa_results (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE REFERENCES candidates(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    issues TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    suggested_fix TEXT NOT NULL DEFAULT '',
                    repair_applied INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS review_decisions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    page_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                    decision TEXT NOT NULL,
                    override_reason TEXT NOT NULL DEFAULT '',
                    reviewer TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _prompt_from_row(row: sqlite3.Row) -> PromptVersion:
        return PromptVersion(
            id=row["id"], prompt_asset_id=row["prompt_asset_id"], name=row["name"],
            version=int(row["version"]), body=row["body"], variables=tuple(json.loads(row["variables"])),
            status=PublishStatus(row["status"]), change_note=row["change_note"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _recipe_from_row(row: sqlite3.Row) -> Recipe:
        return Recipe(
            id=row["id"], name=row["name"], status=PublishStatus(row["status"]),
            prompt_version_id=row["prompt_version_id"], model=row["model"],
            model_params=json.loads(row["model_params"]), template_ids=tuple(json.loads(row["template_ids"])),
            qa_policy=row["qa_policy"], candidate_count=int(row["candidate_count"]),
            created_at=datetime.fromisoformat(row["created_at"]), updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _job_values(job: GenerationJob) -> tuple[object, ...]:
        return (
            job.id, job.project_id, job.page_id, job.recipe_id, job.status.value,
            job.attempt, job.max_attempts, job.error, json.dumps(job.trace, ensure_ascii=False),
            job.created_at.isoformat(), job.updated_at.isoformat(),
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> GenerationJob:
        return GenerationJob(
            id=row["id"], project_id=row["project_id"], page_id=row["page_id"],
            recipe_id=row["recipe_id"], status=JobStatus(row["status"]), attempt=int(row["attempt"]),
            max_attempts=int(row["max_attempts"]), error=row["error"], trace=json.loads(row["trace"]),
            created_at=datetime.fromisoformat(row["created_at"]), updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _candidate_from_row(row: sqlite3.Row) -> Candidate:
        return Candidate(
            id=row["id"], job_id=row["job_id"], project_id=row["project_id"], page_id=row["page_id"],
            candidate_index=int(row["candidate_index"]), base_path=row["base_path"],
            text_layer_path=row["text_layer_path"], composed_path=row["composed_path"],
            prompt=row["prompt"], score=int(row["score"]), rank=int(row["rank"]),
            status=CandidateStatus(row["status"]), metadata=json.loads(row["metadata"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _qa_from_row(row: sqlite3.Row) -> QAResult:
        return QAResult(
            id=row["id"], candidate_id=row["candidate_id"], status=QAStatus(row["status"]),
            score=int(row["score"]), issues=tuple(json.loads(row["issues"])),
            evidence=json.loads(row["evidence"]), suggested_fix=row["suggested_fix"],
            repair_applied=bool(row["repair_applied"]), created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> ReviewDecision:
        return ReviewDecision(
            id=row["id"], project_id=row["project_id"], page_id=row["page_id"],
            candidate_id=row["candidate_id"], decision=ReviewDecisionType(row["decision"]),
            override_reason=row["override_reason"], reviewer=row["reviewer"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
