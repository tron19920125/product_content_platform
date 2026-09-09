from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from .catalog import IMAGE_SIZES, DraftContent, StudioLayer, Tool
from .quality import Review, should_repair
from .workspace import RevisionConflict, StudioWorkspace, timestamp


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Creations:
    """Durable per-candidate jobs, immutable inputs and image lineage.

    The executor can be Codex or a clearly labelled recorded-demo adapter. Neither
    executor controls draft state, repair budgets or the user's current selection.
    """

    def __init__(self, workspace: StudioWorkspace):
        self.workspace = workspace
        with workspace._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS studio_operations (
                    id TEXT PRIMARY KEY, submit_key TEXT NOT NULL UNIQUE,
                    draft_id TEXT NOT NULL REFERENCES studio_drafts(id),
                    kind TEXT NOT NULL, mode TEXT NOT NULL, snapshot TEXT NOT NULL,
                    stopped INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS studio_versions (
                    id TEXT PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES studio_drafts(id),
                    page_id TEXT NOT NULL, operation_id TEXT,
                    parent_id TEXT REFERENCES studio_versions(id), kind TEXT NOT NULL,
                    base_asset_id TEXT NOT NULL REFERENCES studio_assets(id),
                    render_asset_id TEXT NOT NULL REFERENCES studio_assets(id),
                    layers TEXT NOT NULL, review TEXT NOT NULL, provenance TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS studio_selections (
                    draft_id TEXT NOT NULL REFERENCES studio_drafts(id), page_id TEXT NOT NULL,
                    version_id TEXT REFERENCES studio_versions(id), revision INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (draft_id, page_id)
                );
                CREATE TABLE IF NOT EXISTS studio_jobs (
                    id TEXT PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES studio_operations(id),
                    page_id TEXT NOT NULL, variant INTEGER NOT NULL, kind TEXT NOT NULL,
                    status TEXT NOT NULL, repair_used INTEGER NOT NULL DEFAULT 0,
                    source_version_id TEXT REFERENCES studio_versions(id), version_id TEXT REFERENCES studio_versions(id),
                    expected_selection INTEGER NOT NULL, error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS studio_edit_drafts (
                    version_id TEXT PRIMARY KEY REFERENCES studio_versions(id),
                    layers TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS studio_operation_assets (
                    operation_id TEXT NOT NULL REFERENCES studio_operations(id),
                    asset_id TEXT NOT NULL REFERENCES studio_assets(id), PRIMARY KEY(operation_id, asset_id)
                );
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

    def submit(self, draft_id: str, *, submit_key: str, expected_revision: int,
               mode: Literal["demo", "codex"], page_ids: list[str] | None = None,
               source_version_id: str | None = None, instruction: str = "") -> dict:
        if not submit_key.strip() or len(submit_key) > 100 or mode not in {"demo", "codex"}:
            raise ValueError("提交标识或执行方式无效")
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM studio_operations WHERE submit_key=?", (submit_key,)).fetchone()
            if existing:
                previous = json.loads(existing["snapshot"])
                if (existing["draft_id"] != draft_id or existing["mode"] != mode
                        or previous["draft_revision"] != expected_revision
                        or previous["requested_page_ids"] != page_ids
                        or previous["source_version_id"] != source_version_id
                        or previous["instruction"] != instruction):
                    raise RevisionConflict("提交标识已用于其他参数，不能复用")
                return self._operation(db, existing["id"])
            draft = self.workspace._find(db, "studio_drafts", draft_id)
            if draft["deleted_at"]:
                raise ValueError("请先从回收站恢复创作记录，再提交生成")
            if draft["revision"] != expected_revision:
                raise RevisionConflict("输入已变化，请保存并使用最新版本提交")
            content = DraftContent.model_validate_json(draft["content"])
            pages = [page for page in content.pages if not page.skipped and (page_ids is None or page.id in page_ids)]
            if page_ids is not None and (not page_ids or len(set(page_ids)) != len(page_ids) or set(page_ids) != {p.id for p in pages}):
                raise ValueError("请选择当前存在且未跳过的页面")
            if not content.product_asset_ids:
                raise ValueError("请先上传至少一张原始商品图")
            if not pages:
                raise ValueError("请至少保留一个待生成页面")
            if content.tool == Tool.A_PLUS and any(
                not (page.title.strip() or page.body.strip()) or not page.visual_goal.strip()
                for page in pages
            ):
                raise ValueError("请先生成 A+ 模块方案，或手动补齐每个模块的文案与画面描述")
            for fact in content.facts:
                fact.validate_for_generation()
            if any(page.purpose in {"dimensions", "comparison", "package_contents", "brand_story"} for page in pages) and not content.facts:
                raise ValueError("尺寸、规格对比、包装清单或品牌介绍需要事实及来源，请补充、删页或跳过")
            source = None
            if source_version_id:
                source = self._version(db, source_version_id)
                if source["draft_id"] != draft_id or [p.id for p in pages] != [source["page_id"]]:
                    raise ValueError("AI 修改必须针对来源版本所在的单页")
                if not instruction.strip():
                    raise ValueError("请填写 AI 修改要求")
            references = content.product_asset_ids + content.style_asset_ids + ([content.logo_asset_id] if content.logo_asset_id else [])
            if len(references) + bool(source) > self.workspace.settings.max_references:
                raise ValueError("参考图超过总上限；AI 修改还需为底图预留一张位置")
            for asset_id in references:
                self.workspace._find(db, "studio_assets", asset_id)
            identifier, now = str(uuid4()), timestamp()
            snapshot = {
                "content": content.model_dump(mode="json"), "draft_revision": expected_revision,
                "requested_page_ids": page_ids, "source_version_id": source_version_id,
                "instruction": instruction, "pages": [page.model_dump(mode="json") for page in pages],
                "source_layers": source["layers"] if source else [],
            }
            db.execute("INSERT INTO studio_operations VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                       (identifier, submit_key, draft_id, "ai_edit" if source else "generate", mode, encoded(snapshot), now))
            db.executemany("INSERT INTO studio_operation_assets VALUES (?, ?)", [(identifier, value) for value in set(references)])
            for page in pages:
                db.execute("INSERT OR IGNORE INTO studio_selections VALUES (?, ?, NULL, 0)", (draft_id, page.id))
                selection = db.execute("SELECT revision FROM studio_selections WHERE draft_id=? AND page_id=?", (draft_id, page.id)).fetchone()[0]
                for variant in range(1, (1 if source else content.candidate_count) + 1):
                    db.execute("INSERT INTO studio_jobs VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, NULL, ?, '', ?, ?)",
                               (str(uuid4()), identifier, page.id, variant, "ai_edit" if source else "generate", source_version_id, selection, now, now))
            return self._operation(db, identifier)

    def claim(self, operation_id: str | None = None, *, mode: str | None = None) -> dict | None:
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM studio_jobs WHERE status='running'").fetchone()[0] >= 2:
                return None
            row = db.execute("""SELECT j.* FROM studio_jobs j JOIN studio_operations o ON j.operation_id=o.id
                WHERE j.status='queued' AND o.stopped=0 AND (? IS NULL OR o.id=?)
                AND (? IS NULL OR o.mode=?)
                ORDER BY j.created_at, j.variant, j.id LIMIT 1""", (operation_id, operation_id, mode, mode)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE studio_jobs SET status='running', updated_at=? WHERE id=?", (timestamp(), row["id"]))
            result = dict(row)
            result["status"] = "running"
            result["operation"] = self._operation(db, row["operation_id"])
            if row["source_version_id"]:
                result["source_version"] = self._version(db, row["source_version_id"])
            return result

    def complete(self, job_id: str, *, asset_id: str, review: Review, provenance: dict) -> dict:
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self._job(db, job_id)
            if job["version_id"]:
                return self._version(db, job["version_id"])
            if job["status"] not in {"running", "unknown"}:
                raise ValueError("当前任务不能接收结果，请先领取待执行任务")
            asset = self.workspace._find(db, "studio_assets", asset_id)
            operation = self._operation(db, job["operation_id"])
            snapshot = operation["snapshot"]
            source = self._version(db, job["source_version_id"]) if job["source_version_id"] else None
            layers = source["layers"] if source else snapshot["source_layers"]
            page = next(value for value in snapshot["pages"] if value["id"] == job["page_id"])
            output = page.get("output") or snapshot["content"]["output"]
            expected_width, expected_height = IMAGE_SIZES[output["ratio"]][output["resolution"]]
            provenance = dict(provenance)
            provenance.update(
                requested_output={**output, "width": expected_width, "height": expected_height, "quality": "high"},
                actual_output={"width": asset["width"], "height": asset["height"]},
                matches_requested_pixels=(asset["width"], asset["height"]) == (expected_width, expected_height),
            )
            identifier, now = str(uuid4()), timestamp()
            db.execute("INSERT INTO studio_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (identifier, operation["draft_id"], job["page_id"], operation["id"], job["source_version_id"],
                        "repair" if job["kind"] == "repair" else "ai", asset_id, asset_id,
                        encoded(layers), review.model_dump_json(), encoded(provenance), now))
            db.execute("UPDATE studio_jobs SET status='done', version_id=?, updated_at=? WHERE id=?", (identifier, now, job_id))
            selection = db.execute("SELECT * FROM studio_selections WHERE draft_id=? AND page_id=?", (operation["draft_id"], job["page_id"])).fetchone()
            current = self._version(db, selection["version_id"]) if selection["version_id"] else None
            current_score = current["review"]["score"] if current else None
            better = current is None or (review.score is not None and (current_score is None or review.score > current_score))
            if selection["revision"] == job["expected_selection"] and better:
                db.execute("UPDATE studio_selections SET version_id=? WHERE draft_id=? AND page_id=?", (identifier, operation["draft_id"], job["page_id"]))
            if should_repair(review, repair_used=bool(job["repair_used"]), stopped=bool(operation["stopped"])):
                db.execute("UPDATE studio_jobs SET repair_used=1 WHERE id=?", (job_id,))
                db.execute("INSERT INTO studio_jobs VALUES (?, ?, ?, ?, 'repair', 'queued', 1, ?, NULL, ?, '', ?, ?)",
                           (str(uuid4()), operation["id"], job["page_id"], job["variant"], identifier, job["expected_selection"], now, now))
            return self._version(db, identifier)

    def fail(self, job_id: str, *, message: str, outcome_known: bool) -> None:
        with self.workspace._connect() as db:
            row = self._job(db, job_id)
            if row["status"] != "running":
                raise ValueError("只有正在执行的任务可以标记失败")
            db.execute("UPDATE studio_jobs SET status=?, error=?, updated_at=? WHERE id=?", ("failed" if outcome_known else "unknown", message[:2000], timestamp(), job_id))

    def retry(self, job_id: str) -> dict:
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._job(db, job_id)
            if row["status"] != "failed":
                raise ValueError("仅能重试已确认失败的单项；结果不明的任务不能自动重发")
            operation = self._operation(db, row["operation_id"])
            if operation["stopped"]:
                raise ValueError("该次任务已停止，请明确发起新生成")
            db.execute("UPDATE studio_jobs SET status='queued', error='', updated_at=? WHERE id=?", (timestamp(), job_id))
            return dict(self._job(db, job_id))

    def stop(self, operation_id: str) -> dict:
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._operation(db, operation_id)
            db.execute("UPDATE studio_operations SET stopped=1 WHERE id=?", (operation_id,))
            db.execute("UPDATE studio_jobs SET status='stopped' WHERE operation_id=? AND status='queued'", (operation_id,))
            return self._operation(db, operation_id)

    def recover(self) -> int:
        with self.workspace._connect() as db:
            # A process crash does not establish whether an external request ran.
            return db.execute("UPDATE studio_jobs SET status='unknown', error='服务中断，外部执行结果待确认' WHERE status='running'").rowcount

    def snapshot(self, draft_id: str) -> dict:
        with self.workspace._connect() as db:
            self.workspace._find(db, "studio_drafts", draft_id)
            operations = [self._operation(db, row[0]) for row in db.execute("SELECT id FROM studio_operations WHERE draft_id=? ORDER BY created_at DESC", (draft_id,))]
            versions = [self._version(db, row[0]) for row in db.execute("SELECT id FROM studio_versions WHERE draft_id=? ORDER BY created_at", (draft_id,))]
            selections = [dict(row) for row in db.execute("SELECT * FROM studio_selections WHERE draft_id=?", (draft_id,))]
            review_tasks = [dict(row) for row in db.execute("""SELECT r.* FROM studio_review_tasks r
                JOIN studio_versions v ON v.id=r.version_id WHERE v.draft_id=? ORDER BY r.created_at""", (draft_id,))]
            return {"operations": operations, "versions": versions, "selections": selections, "review_tasks": review_tasks}

    def history(self, *, trash: bool = False) -> list[dict]:
        records = self.workspace.list_drafts(trash=trash)
        with self.workspace._connect() as db:
            for record in records:
                statuses = [row[0] for row in db.execute("""SELECT j.status FROM studio_jobs j
                    JOIN studio_operations o ON o.id=j.operation_id WHERE o.draft_id=?""", (record["id"],))]
                version_count = db.execute("SELECT COUNT(*) FROM studio_versions WHERE draft_id=?", (record["id"],)).fetchone()[0]
                if "running" in statuses:
                    status = "processing"
                elif any(value == "unknown" for value in statuses):
                    status = "unknown"
                elif "queued" in statuses:
                    status = "queued"
                elif any(value == "failed" for value in statuses) and version_count:
                    status = "partial"
                elif any(value == "failed" for value in statuses):
                    status = "failed"
                elif version_count:
                    status = "completed"
                else:
                    status = "draft"
                selected = db.execute("""SELECT v.render_asset_id FROM studio_selections s
                    JOIN studio_versions v ON v.id=s.version_id
                    WHERE s.draft_id=? ORDER BY v.created_at DESC LIMIT 1""", (record["id"],)).fetchone()
                record.update(
                    history_status=status,
                    result_count=version_count,
                    thumbnail_url=f"/api/studio/assets/{selected[0]}/preview" if selected else None,
                )
        return records

    def select(self, draft_id: str, page_id: str, version_id: str) -> dict:
        with self.workspace._connect() as db:
            version = self._version(db, version_id)
            if (version["draft_id"], version["page_id"]) != (draft_id, page_id):
                raise ValueError("不能选用其他页面的版本")
            db.execute("UPDATE studio_selections SET version_id=?, revision=revision+1 WHERE draft_id=? AND page_id=?", (version_id, draft_id, page_id))
        return self.snapshot(draft_id)

    def get_version(self, identifier: str) -> dict:
        with self.workspace._connect() as db:
            return self._version(db, identifier)

    def update_review(self, version_id: str, review: Review) -> dict:
        """Attach a fresh AI review and apply the same one-repair policy once."""
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = self._version(db, version_id)
            if version["kind"] == "manual":
                raise ValueError("手动编辑版本不进行自动质检")
            db.execute("UPDATE studio_versions SET review=? WHERE id=?", (review.model_dump_json(), version_id))
            job = db.execute("SELECT * FROM studio_jobs WHERE version_id=?", (version_id,)).fetchone()
            if job:
                operation = self._operation(db, job["operation_id"])
                already_queued = db.execute("SELECT 1 FROM studio_jobs WHERE source_version_id=? AND kind='repair'", (version_id,)).fetchone()
                if not already_queued and should_repair(review, repair_used=bool(job["repair_used"]), stopped=bool(operation["stopped"])):
                    now = timestamp()
                    db.execute("UPDATE studio_jobs SET repair_used=1 WHERE id=?", (job["id"],))
                    db.execute("INSERT INTO studio_jobs VALUES (?, ?, ?, ?, 'repair', 'queued', 1, ?, NULL, ?, '', ?, ?)",
                               (str(uuid4()), operation["id"], job["page_id"], job["variant"], version_id, job["expected_selection"], now, now))
            return self._version(db, version_id)

    def restore_work(self, entry: dict) -> dict:
        """Create an independent editable draft/version graph from a library snapshot."""
        if entry.get("kind") != "work":
            raise ValueError("只有作品快照可以继续编辑")
        payload = entry.get("payload", {})
        content = DraftContent.model_validate(payload.get("content"))
        versions = payload.get("versions")
        if not isinstance(versions, list) or not versions:
            raise ValueError("该素材只有预览图，没有可继续编辑的版本数据")
        page_ids = {page.id for page in content.pages}
        if any(not isinstance(version, dict) or version.get("page_id") not in page_ids for version in versions):
            raise ValueError("作品版本与页面结构不一致，不能继续编辑")
        draft_id, now = str(uuid4()), timestamp()
        mapping: dict[str, str] = {}
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            references = content.product_asset_ids + content.style_asset_ids + ([content.logo_asset_id] if content.logo_asset_id else [])
            if len(references) > self.workspace.settings.max_references:
                raise ValueError("作品引用超过当前配置上限")
            for identifier in references:
                self.workspace._find(db, "studio_assets", identifier)
            db.execute("""INSERT INTO studio_drafts
                (id, tool, revision, content, created_at, updated_at, deleted_at)
                VALUES (?, ?, 1, ?, ?, ?, NULL)""",
                (draft_id, content.tool.value, content.model_dump_json(), now, now))
            db.executemany("INSERT INTO studio_draft_assets VALUES (?, ?)", [(draft_id, value) for value in references])
            for source in versions:
                if source.get("kind") not in {"ai", "repair", "manual"}:
                    raise ValueError("作品包含未知版本类型")
                base, rendered = source.get("base_asset_id"), source.get("render_asset_id")
                self.workspace._find(db, "studio_assets", base)
                self.workspace._find(db, "studio_assets", rendered)
                layers = self._validate_layers(source.get("layers", []))
                for layer in layers:
                    if layer.get("asset_id"):
                        self.workspace._find(db, "studio_assets", layer["asset_id"])
                review_data = {key: value for key, value in source.get("review", {}).items() if key != "score"}
                review = Review.model_validate(review_data)
                version_id = str(uuid4()); mapping[source.get("id", version_id)] = version_id
                provenance = dict(source.get("provenance", {}))
                provenance.update(copied_from=source.get("id"), library_entry_id=entry["id"])
                db.execute("INSERT INTO studio_versions VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?)",
                           (version_id, draft_id, source["page_id"], source["kind"], base, rendered,
                            encoded(layers), review.model_dump_json(), encoded(provenance), now))
            for source in versions:
                new_id = mapping[source.get("id")]
                db.execute("INSERT OR REPLACE INTO studio_selections VALUES (?, ?, ?, 0)",
                           (draft_id, source["page_id"], new_id))
        return {"draft": self.workspace.get_draft(draft_id), "results": self.snapshot(draft_id)}

    def change_draft(self, draft_id: str, *, action: str) -> dict:
        """Apply the recoverable history lifecycle without touching library snapshots."""
        purge_assets: set[str] = set()
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.workspace._find(db, "studio_drafts", draft_id)
            if action == "trash":
                now = timestamp()
                db.execute("UPDATE studio_operations SET stopped=1 WHERE draft_id=?", (draft_id,))
                db.execute("""UPDATE studio_jobs SET status='stopped', updated_at=?
                    WHERE operation_id IN (SELECT id FROM studio_operations WHERE draft_id=?)
                    AND status='queued'""", (now, draft_id))
                # Repeated deletion does not extend the 30-day retention period.
                db.execute("UPDATE studio_drafts SET deleted_at=COALESCE(deleted_at, ?), updated_at=? WHERE id=?", (now, now, draft_id))
            elif action == "restore":
                if row["deleted_at"] and datetime.fromisoformat(row["deleted_at"]) + timedelta(days=30) <= datetime.now(timezone.utc):
                    raise ValueError("记录已超过 30 天保留期限，不能恢复")
                db.execute("UPDATE studio_drafts SET deleted_at=NULL, updated_at=? WHERE id=?", (timestamp(), draft_id))
            elif action == "purge":
                if not row["deleted_at"]:
                    raise ValueError("请先将创作记录移入回收站")
                inflight = db.execute("""SELECT COUNT(*) FROM studio_jobs
                    WHERE operation_id IN (SELECT id FROM studio_operations WHERE draft_id=?)
                    AND status IN ('running', 'unknown')""", (draft_id,)).fetchone()[0]
                if inflight:
                    raise ValueError("仍有在途或结果不明任务，待结果归档后才能彻底删除")
                purge_assets.update(row[0] for row in db.execute("SELECT asset_id FROM studio_draft_assets WHERE draft_id=?", (draft_id,)))
                purge_assets.update(row[0] for row in db.execute("""SELECT asset_id FROM studio_operation_assets
                    WHERE operation_id IN (SELECT id FROM studio_operations WHERE draft_id=?)""", (draft_id,)))
                for version_row in db.execute("SELECT base_asset_id, render_asset_id, layers FROM studio_versions WHERE draft_id=?", (draft_id,)):
                    purge_assets.update((version_row["base_asset_id"], version_row["render_asset_id"]))
                    purge_assets.update(layer["asset_id"] for layer in json.loads(version_row["layers"])
                                        if isinstance(layer, dict) and isinstance(layer.get("asset_id"), str))
                db.execute("DELETE FROM studio_edit_drafts WHERE version_id IN (SELECT id FROM studio_versions WHERE draft_id=?)", (draft_id,))
                db.execute("DELETE FROM studio_review_tasks WHERE version_id IN (SELECT id FROM studio_versions WHERE draft_id=?)", (draft_id,))
                db.execute("DELETE FROM studio_selections WHERE draft_id=?", (draft_id,))
                db.execute("DELETE FROM studio_jobs WHERE operation_id IN (SELECT id FROM studio_operations WHERE draft_id=?)", (draft_id,))
                db.execute("DELETE FROM studio_operation_assets WHERE operation_id IN (SELECT id FROM studio_operations WHERE draft_id=?)", (draft_id,))
                db.execute("DELETE FROM studio_operations WHERE draft_id=?", (draft_id,))
                db.execute("UPDATE studio_versions SET parent_id=NULL WHERE draft_id=?", (draft_id,))
                db.execute("DELETE FROM studio_versions WHERE draft_id=?", (draft_id,))
                db.execute("DELETE FROM studio_draft_assets WHERE draft_id=?", (draft_id,))
                db.execute("DELETE FROM studio_drafts WHERE id=?", (draft_id,))
                result = {"id": draft_id, "deleted": True}
            else:
                raise ValueError("未知创作记操作")
        if action == "purge":
            self.workspace.collect_unreferenced_assets(purge_assets)
            return result
        return self.workspace.get_draft(draft_id)

    def clean_expired_drafts(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with self.workspace._connect() as db:
            identifiers = [row[0] for row in db.execute("""SELECT id FROM studio_drafts d
                WHERE deleted_at IS NOT NULL AND deleted_at<=?
                AND NOT EXISTS (
                    SELECT 1 FROM studio_jobs j JOIN studio_operations o ON j.operation_id=o.id
                    WHERE o.draft_id=d.id AND j.status IN ('running', 'unknown')
                )""", (cutoff,))]
        for identifier in identifiers:
            self.change_draft(identifier, action="purge")
        return len(identifiers)

    def save_edit(self, version_id: str, *, layers: list[dict], expected_revision: int) -> dict:
        layers = self._validate_layers(layers)
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._version(db, version_id)
            for layer in layers:
                if layer.get("asset_id"):
                    self.workspace._find(db, "studio_assets", layer["asset_id"])
            previous = db.execute("SELECT revision FROM studio_edit_drafts WHERE version_id=?", (version_id,)).fetchone()
            if (previous[0] if previous else 0) != expected_revision:
                raise RevisionConflict("编辑草稿已更新，请重新加载")
            db.execute("INSERT INTO studio_edit_drafts VALUES (?, ?, ?, ?) ON CONFLICT(version_id) DO UPDATE SET layers=excluded.layers, revision=excluded.revision, updated_at=excluded.updated_at",
                       (version_id, encoded(layers), expected_revision + 1, timestamp()))
        return self.get_edit(version_id)

    def get_edit(self, version_id: str) -> dict:
        with self.workspace._connect() as db:
            version = self._version(db, version_id)
            row = db.execute("SELECT * FROM studio_edit_drafts WHERE version_id=?", (version_id,)).fetchone()
            return {**dict(row), "layers": json.loads(row["layers"])} if row else {"version_id": version_id, "layers": version["layers"], "revision": 0}

    def apply_edit(self, version_id: str, *, expected_revision: int, rendered_asset_id: str) -> dict:
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            source = self._version(db, version_id)
            edit = db.execute("SELECT * FROM studio_edit_drafts WHERE version_id=?", (version_id,)).fetchone()
            if not edit or edit["revision"] != expected_revision:
                raise RevisionConflict("请先保存当前编辑草稿，再完成编辑")
            asset = self.workspace._find(db, "studio_assets", rendered_asset_id)
            base = self.workspace._find(db, "studio_assets", source["base_asset_id"])
            if (asset["width"], asset["height"]) != (base["width"], base["height"]):
                raise ValueError("手工合成图必须保持底图像素尺寸")
            identifier = str(uuid4())
            db.execute("INSERT INTO studio_versions VALUES (?, ?, ?, NULL, ?, 'manual', ?, ?, ?, ?, ?, ?)",
                       (identifier, source["draft_id"], source["page_id"], version_id, source["base_asset_id"],
                        rendered_asset_id, edit["layers"], encoded({k: v for k, v in source["review"].items() if k != "score"}),
                        encoded({"provider": "manual", "note": "人工编辑，未重新质检"}), timestamp()))
            db.execute("UPDATE studio_selections SET version_id=?, revision=revision+1 WHERE draft_id=? AND page_id=?", (identifier, source["draft_id"], source["page_id"]))
            db.execute("DELETE FROM studio_edit_drafts WHERE version_id=?", (version_id,))
            return self._version(db, identifier)

    def discard_edit(self, version_id: str) -> None:
        with self.workspace._connect() as db:
            db.execute("DELETE FROM studio_edit_drafts WHERE version_id=?", (version_id,))

    @staticmethod
    def _validate_layers(layers: list[dict]) -> list[dict]:
        if len(layers) > 100 or len(encoded(layers).encode()) > 500_000:
            raise ValueError("编辑图层过多或内容过大")
        normalized = [StudioLayer.model_validate(layer).model_dump(mode="json", exclude_none=True) for layer in layers]
        identifiers = [layer["id"] for layer in normalized]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("图层标识无效或重复")
        return normalized

    @staticmethod
    def _job(db, identifier):
        row = db.execute("SELECT * FROM studio_jobs WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("任务不存在")
        return row

    def _operation(self, db, identifier) -> dict:
        row = db.execute("SELECT * FROM studio_operations WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("生成记录不存在")
        return {**dict(row), "snapshot": json.loads(row["snapshot"]), "jobs": [dict(job) for job in db.execute("SELECT * FROM studio_jobs WHERE operation_id=? ORDER BY created_at, variant", (identifier,))]}

    @staticmethod
    def _version(db, identifier) -> dict:
        row = db.execute("SELECT * FROM studio_versions WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("图片版本不存在")
        result = dict(row)
        result["layers"] = json.loads(row["layers"])
        result["review"] = Review.model_validate_json(row["review"]).public()
        result["provenance"] = json.loads(row["provenance"])
        asset = db.execute("SELECT width, height FROM studio_assets WHERE id=?", (row["render_asset_id"],)).fetchone()
        result["width"], result["height"] = asset["width"], asset["height"]
        result["image_url"] = f"/api/studio/assets/{row['render_asset_id']}/source"
        result["base_url"] = f"/api/studio/assets/{row['base_asset_id']}/source"
        result["score_label"] = "AI 底图评分" if row["kind"] == "manual" else "AI 评分"
        return result
