from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from product_content_platform.domain import (
    Asset,
    AssetUsage,
    Batch,
    BatchItem,
    BatchItemStatus,
    BatchStatus,
    PageItem,
    PagePlan,
    PlanningRun,
    PlanningRunStatus,
    PageStatus,
    PageType,
    ProductProfile,
    Project,
    ProjectStatus,
)


class SQLitePlatformRepository:
    """SQLite adapter for project and batch aggregate persistence."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def save_project(self, project: Project) -> None:
        with self._connect() as connection:
            self._insert_project(connection, project)

    def get_project(self, project_id: str) -> Project | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._project_from_row(row) if row else None

    def list_projects(self) -> list[Project]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return [self._project_from_row(row) for row in rows]

    def update_project(self, project: Project) -> None:
        with self._connect() as connection:
            self._update_project(connection, project)

    def save_asset(self, asset: Asset, project: Project) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO assets
                    (id, project_id, usage, file_name, mime_type, storage_path, size_bytes,
                     source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset.id,
                    asset.project_id,
                    asset.usage.value,
                    asset.file_name,
                    asset.mime_type,
                    asset.storage_path,
                    asset.size_bytes,
                    asset.source,
                    asset.created_at.isoformat(),
                ),
            )
            self._update_project(connection, project)

    def get_asset(self, asset_id: str) -> Asset | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        return self._asset_from_row(row) if row else None

    def list_assets(self, project_id: str) -> list[Asset]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM assets WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
        return [self._asset_from_row(row) for row in rows]

    def save_plan(self, plan: PagePlan, project: Project) -> None:
        items = [
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
        ]
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO page_plans
                    (id, project_id, version, items, layout_library_id, confirmed, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    id = excluded.id,
                    version = excluded.version,
                    items = excluded.items,
                    layout_library_id = excluded.layout_library_id,
                    confirmed = excluded.confirmed,
                    updated_at = excluded.updated_at
                """,
                (
                    plan.id,
                    plan.project_id,
                    plan.version,
                    json.dumps(items, ensure_ascii=False),
                    plan.layout_library_id,
                    int(plan.confirmed),
                    plan.created_at.isoformat(),
                    plan.updated_at.isoformat(),
                ),
            )
            self._update_project(connection, project)

    def get_plan(self, project_id: str) -> PagePlan | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM page_plans WHERE project_id = ?", (project_id,)).fetchone()
        if row is None:
            return None
        items = tuple(
            PageItem(
                id=item["id"],
                order=int(item["order"]),
                page_type=PageType(item["page_type"]),
                title=item["title"],
                body=item["body"],
                visual_goal=item["visual_goal"],
                template_id=item["template_id"],
                heading_level=int(item.get("heading_level", 1)),
                status=PageStatus(item.get("status", "draft")),
            )
            for item in json.loads(row["items"])
        )
        return PagePlan(
            id=row["id"],
            project_id=row["project_id"],
            version=int(row["version"]),
            items=items,
            layout_library_id=row["layout_library_id"],
            confirmed=bool(row["confirmed"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def save_planning_run(self, run: PlanningRun) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO planning_runs
                    (id, project_id, status, layout_library_id, base_plan_version,
                     input_snapshot, suggestion, error, degraded, applied_fields,
                     applied_plan_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status, suggestion=excluded.suggestion,
                    error=excluded.error, degraded=excluded.degraded,
                    applied_fields=excluded.applied_fields,
                    applied_plan_version=excluded.applied_plan_version,
                    updated_at=excluded.updated_at
                """,
                (
                    run.id, run.project_id, run.status.value, run.layout_library_id,
                    run.base_plan_version, json.dumps(run.input_snapshot, ensure_ascii=False),
                    json.dumps(run.suggestion, ensure_ascii=False), run.error, int(run.degraded),
                    json.dumps(run.applied_fields, ensure_ascii=False), run.applied_plan_version,
                    run.created_at.isoformat(), run.updated_at.isoformat(),
                ),
            )

    def get_planning_run(self, run_id: str) -> PlanningRun | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM planning_runs WHERE id = ?", (run_id,)).fetchone()
        return self._planning_run_from_row(row) if row else None

    def list_planning_runs(self, project_id: str) -> list[PlanningRun]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM planning_runs WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [self._planning_run_from_row(row) for row in rows]

    def save_batch(self, batch: Batch, projects: list[Project]) -> None:
        with self._connect() as connection:
            for project in projects:
                self._insert_project(connection, project)
            connection.execute(
                """
                INSERT INTO batches (id, name, status, common_config, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    batch.id,
                    batch.name,
                    batch.status.value,
                    json.dumps(batch.common_config, ensure_ascii=False),
                    batch.created_at.isoformat(),
                    batch.updated_at.isoformat(),
                ),
            )
            connection.executemany(
                """
                INSERT INTO batch_items
                    (id, batch_id, project_id, sku, status, override_config, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id,
                        item.batch_id,
                        item.project_id,
                        item.sku,
                        item.status.value,
                        json.dumps(item.override_config, ensure_ascii=False),
                        item.error,
                    )
                    for item in batch.items
                ],
            )

    def get_batch(self, batch_id: str) -> Batch | None:
        with self._connect() as connection:
            batch_row = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
            if batch_row is None:
                return None
            item_rows = connection.execute(
                "SELECT * FROM batch_items WHERE batch_id = ? ORDER BY rowid",
                (batch_id,),
            ).fetchall()
        return self._batch_from_rows(batch_row, item_rows)

    def list_batches(self) -> list[Batch]:
        with self._connect() as connection:
            batch_rows = connection.execute("SELECT * FROM batches ORDER BY created_at DESC").fetchall()
            item_rows = connection.execute("SELECT * FROM batch_items ORDER BY rowid").fetchall()
        items_by_batch: dict[str, list[sqlite3.Row]] = {}
        for row in item_rows:
            items_by_batch.setdefault(row["batch_id"], []).append(row)
        return [self._batch_from_rows(row, items_by_batch.get(row["id"], [])) for row in batch_rows]

    def update_batch_item(
        self,
        batch_id: str,
        item_id: str,
        status: BatchItemStatus,
        error: str = "",
    ) -> Batch | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE batch_items SET status = ?, error = ?
                WHERE id = ? AND batch_id = ?
                """,
                (status.value, error, item_id, batch_id),
            )
            if cursor.rowcount == 0:
                return None

            status_rows = connection.execute(
                "SELECT status FROM batch_items WHERE batch_id = ?",
                (batch_id,),
            ).fetchall()
            aggregate_status = self._derive_batch_status(
                [BatchItemStatus(row["status"]) for row in status_rows]
            )
            connection.execute(
                "UPDATE batches SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (aggregate_status.value, batch_id),
            )

        return self.get_batch(batch_id)

    def set_batch_status(self, batch_id: str, status: str) -> Batch | None:
        BatchStatus(status)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE batches SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status, batch_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_batch(batch_id)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    common_config TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS batch_items (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    sku TEXT NOT NULL,
                    status TEXT NOT NULL,
                    override_config TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    UNIQUE(batch_id, sku)
                );

                CREATE INDEX IF NOT EXISTS idx_batch_items_batch_id ON batch_items(batch_id);

                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    usage TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user_upload',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_assets_project_id ON assets(project_id);

                CREATE TABLE IF NOT EXISTS page_plans (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    items TEXT NOT NULL,
                    layout_library_id TEXT NOT NULL DEFAULT 'library-square-2048',
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS planning_runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    layout_library_id TEXT NOT NULL,
                    base_plan_version INTEGER NOT NULL DEFAULT 0,
                    input_snapshot TEXT NOT NULL,
                    suggestion TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    degraded INTEGER NOT NULL DEFAULT 0,
                    applied_fields TEXT NOT NULL DEFAULT '{}',
                    applied_plan_version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_planning_runs_project ON planning_runs(project_id, created_at DESC);
                """
            )
            asset_columns = {row[1] for row in connection.execute("PRAGMA table_info(assets)").fetchall()}
            if "source" not in asset_columns:
                connection.execute("ALTER TABLE assets ADD COLUMN source TEXT NOT NULL DEFAULT 'user_upload'")
            if "authorization_status" in asset_columns:
                connection.execute("ALTER TABLE assets DROP COLUMN authorization_status")
            plan_columns = {row[1] for row in connection.execute("PRAGMA table_info(page_plans)").fetchall()}
            if "layout_library_id" not in plan_columns:
                connection.execute(
                    "ALTER TABLE page_plans ADD COLUMN layout_library_id TEXT NOT NULL DEFAULT 'library-square-2048'"
                )

    @staticmethod
    def _insert_project(connection: sqlite3.Connection, project: Project) -> None:
        connection.execute(
            """
            INSERT INTO projects (id, name, status, profile, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project.id,
                project.name,
                project.status.value,
                json.dumps(project.profile.to_dict(), ensure_ascii=False),
                project.created_at.isoformat(),
                project.updated_at.isoformat(),
            ),
        )

    @staticmethod
    def _update_project(connection: sqlite3.Connection, project: Project) -> None:
        connection.execute(
            """
            UPDATE projects SET name = ?, status = ?, profile = ?, updated_at = ? WHERE id = ?
            """,
            (
                project.name,
                project.status.value,
                json.dumps(project.profile.to_dict(), ensure_ascii=False),
                project.updated_at.isoformat(),
                project.id,
            ),
        )

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> Asset:
        return Asset(
            id=row["id"],
            project_id=row["project_id"],
            usage=AssetUsage(row["usage"]),
            file_name=row["file_name"],
            mime_type=row["mime_type"],
            storage_path=row["storage_path"],
            size_bytes=int(row["size_bytes"]),
            source=row["source"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _planning_run_from_row(row: sqlite3.Row) -> PlanningRun:
        return PlanningRun(
            id=row["id"], project_id=row["project_id"], status=PlanningRunStatus(row["status"]),
            layout_library_id=row["layout_library_id"], base_plan_version=int(row["base_plan_version"]),
            input_snapshot=json.loads(row["input_snapshot"]), suggestion=json.loads(row["suggestion"]),
            error=row["error"], degraded=bool(row["degraded"]),
            applied_fields=json.loads(row["applied_fields"]),
            applied_plan_version=int(row["applied_plan_version"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            status=ProjectStatus(row["status"]),
            profile=ProductProfile.from_dict(json.loads(row["profile"])),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _batch_from_rows(batch_row: sqlite3.Row, item_rows: list[sqlite3.Row]) -> Batch:
        items = tuple(
            BatchItem(
                id=row["id"],
                batch_id=row["batch_id"],
                project_id=row["project_id"],
                sku=row["sku"],
                status=BatchItemStatus(row["status"]),
                override_config=json.loads(row["override_config"]),
                error=row["error"],
            )
            for row in item_rows
        )
        return Batch(
            id=batch_row["id"],
            name=batch_row["name"],
            status=BatchStatus(batch_row["status"]),
            common_config=json.loads(batch_row["common_config"]),
            items=items,
            created_at=datetime.fromisoformat(batch_row["created_at"]),
            updated_at=datetime.fromisoformat(batch_row["updated_at"]),
        )

    @staticmethod
    def _derive_batch_status(statuses: list[BatchItemStatus]) -> BatchStatus:
        if statuses and all(status is BatchItemStatus.COMPLETED for status in statuses):
            return BatchStatus.COMPLETED
        if any(status is BatchItemStatus.RUNNING for status in statuses):
            return BatchStatus.RUNNING
        if any(status is BatchItemStatus.NEEDS_REVIEW for status in statuses):
            return BatchStatus.NEEDS_REVIEW
        if any(status is BatchItemStatus.FAILED for status in statuses):
            return BatchStatus.PARTIAL_FAILED
        return BatchStatus.READY
    PageItem,
    PagePlan,
    PageStatus,
    PageType,
