from __future__ import annotations

from uuid import uuid4

from .creations import Creations
from .quality import Review
from .workspace import StudioWorkspace, timestamp


class QualityChecks:
    """Retryable AI-only review queue, independent from image generation calls."""

    def __init__(self, workspace: StudioWorkspace, creations: Creations):
        self.workspace, self.creations = workspace, creations
        with workspace._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS studio_review_tasks (
                    id TEXT PRIMARY KEY,
                    version_id TEXT NOT NULL REFERENCES studio_versions(id),
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS studio_reviews_by_status
                    ON studio_review_tasks (status, created_at);
            """)

    def request(self, version_id: str) -> dict:
        version = self.creations.get_version(version_id)
        if version["kind"] == "manual":
            raise ValueError("手动编辑版本不进行自动质检")
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("""SELECT * FROM studio_review_tasks
                WHERE version_id=? AND status IN ('queued', 'running')
                ORDER BY created_at DESC LIMIT 1""", (version_id,)).fetchone()
            if active:
                return dict(active)
            identifier, now = str(uuid4()), timestamp()
            db.execute("INSERT INTO studio_review_tasks VALUES (?, ?, 'queued', 0, '', ?, ?)",
                       (identifier, version_id, now, now))
            return dict(db.execute("SELECT * FROM studio_review_tasks WHERE id=?", (identifier,)).fetchone())

    def claim(self) -> dict | None:
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM studio_review_tasks WHERE status='queued' ORDER BY created_at, id LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE studio_review_tasks SET status='running', attempt=attempt+1, updated_at=? WHERE id=?",
                       (timestamp(), row["id"]))
            task = dict(db.execute("SELECT * FROM studio_review_tasks WHERE id=?", (row["id"],)).fetchone())
        task["version"] = self.creations.get_version(task["version_id"])
        return task

    def complete(self, identifier: str, review: Review) -> dict:
        with self.workspace._connect() as db:
            task = db.execute("SELECT * FROM studio_review_tasks WHERE id=?", (identifier,)).fetchone()
            if not task:
                raise KeyError("质检任务不存在")
            if task["status"] == "done":
                return self.creations.get_version(task["version_id"])
            if task["status"] != "running":
                raise ValueError("质检任务尚未领取")
            version_id = task["version_id"]
        version = self.creations.update_review(version_id, review)
        with self.workspace._connect() as db:
            db.execute("UPDATE studio_review_tasks SET status='done', error='', updated_at=? WHERE id=?", (timestamp(), identifier))
        return version

    def fail(self, identifier: str, *, message: str) -> dict:
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT * FROM studio_review_tasks WHERE id=?", (identifier,)).fetchone()
            if not task:
                raise KeyError("质检任务不存在")
            if task["status"] != "running":
                raise ValueError("只能标记正在执行的质检任务")
            status = "queued" if task["attempt"] < 3 else "failed"
            db.execute("UPDATE studio_review_tasks SET status=?, error=?, updated_at=? WHERE id=?",
                       (status, message[:2000], timestamp(), identifier))
            result = dict(db.execute("SELECT * FROM studio_review_tasks WHERE id=?", (identifier,)).fetchone())
        if status == "failed":
            self.creations.update_review(task["version_id"], Review(
                status="unavailable", source="quality-check",
                note="质检服务已自动尝试 3 次，仍未完成；未伪造分数，可手动重检。",
            ))
        return result

    def status_for(self, version_id: str) -> dict | None:
        with self.workspace._connect() as db:
            row = db.execute("SELECT * FROM studio_review_tasks WHERE version_id=? ORDER BY created_at DESC LIMIT 1", (version_id,)).fetchone()
        return dict(row) if row else None

    def recover(self) -> int:
        # Repeating a read-only assessment is safe; attempt count is retained.
        with self.workspace._connect() as db:
            return db.execute("""UPDATE studio_review_tasks SET status='queued',
                error='服务中断，已安全重新排队', updated_at=? WHERE status='running'""", (timestamp(),)).rowcount
