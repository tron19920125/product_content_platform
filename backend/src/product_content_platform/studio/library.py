from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from .workspace import StudioWorkspace, timestamp


LibraryKind = Literal["product", "style", "logo", "work", "style_preset"]


class Library:
    """Independent saved snapshots and a 30-day recoverable trash.

    Physical images remain protected by foreign-key references, not list visibility.
    Saving and restoring an entry never calls a model or re-evaluates a score.
    """

    def __init__(self, workspace: StudioWorkspace):
        self.workspace = workspace
        with workspace._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS studio_library (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS studio_library_assets (
                    entry_id TEXT NOT NULL REFERENCES studio_library(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES studio_assets(id),
                    PRIMARY KEY(entry_id, asset_id)
                );
            """)

    def save(self, *, name: str, kind: LibraryKind, payload: dict, asset_ids: list[str]) -> dict:
        if kind not in {"product", "style", "logo", "work", "style_preset"}:
            raise ValueError("未知素材分类")
        name = name.strip()
        if not name or len(name) > 200:
            raise ValueError("名称不能为空且不能超过 200 字")
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(serialized.encode()) > 2_000_000:
            raise ValueError("作品数据过大")
        fingerprint = hashlib.sha256((kind + serialized).encode()).hexdigest()
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM studio_library WHERE fingerprint=? AND deleted_at IS NULL", (fingerprint,)).fetchone()
            if old:
                return {**self._public(old), "already_saved": True}
            for asset_id in set(asset_ids):
                self.workspace._find(db, "studio_assets", asset_id)
            identifier, now = str(uuid4()), timestamp()
            db.execute("INSERT INTO studio_library VALUES (?, ?, ?, ?, ?, ?, ?, NULL)", (identifier, name, kind, serialized, fingerprint, now, now))
            db.executemany("INSERT INTO studio_library_assets VALUES (?, ?)", [(identifier, value) for value in set(asset_ids)])
            return self._public(db.execute("SELECT * FROM studio_library WHERE id=?", (identifier,)).fetchone())

    def list(self, *, trash: bool = False, kind: str = "", query: str = "") -> list[dict]:
        with self.workspace._connect() as db:
            rows = db.execute("SELECT * FROM studio_library ORDER BY updated_at DESC").fetchall()
        return [self._public(row) for row in rows
                if bool(row["deleted_at"]) == trash and (not kind or row["kind"] == kind)
                and query.casefold() in (row["name"] + row["payload"]).casefold()]

    def get(self, identifier: str) -> dict:
        with self.workspace._connect() as db:
            row = db.execute("SELECT * FROM studio_library WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("素材库条目不存在")
        return self._public(row)

    def change(self, identifier: str, *, action: str, name: str = "") -> dict:
        purge_assets: set[str] = set()
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM studio_library WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise KeyError("素材库条目不存在")
            if action == "rename":
                if not name.strip() or len(name) > 200:
                    raise ValueError("名称不能为空且不能超过 200 字")
                db.execute("UPDATE studio_library SET name=?, updated_at=? WHERE id=?", (name.strip(), timestamp(), identifier))
            elif action == "trash":
                # Repeated deletes must not reset the retention deadline.
                db.execute("UPDATE studio_library SET deleted_at=COALESCE(deleted_at, ?), updated_at=? WHERE id=?", (timestamp(), timestamp(), identifier))
            elif action == "restore":
                if row["deleted_at"] and self._expired(row["deleted_at"]):
                    raise ValueError("条目已超过 30 天保留期限，不能恢复")
                db.execute("UPDATE studio_library SET deleted_at=NULL, updated_at=? WHERE id=?", (timestamp(), identifier))
            elif action == "purge":
                if not row["deleted_at"]:
                    raise ValueError("请先移入回收站，再确认彻底删除")
                purge_assets = {value[0] for value in db.execute("SELECT asset_id FROM studio_library_assets WHERE entry_id=?", (identifier,))}
                db.execute("DELETE FROM studio_library WHERE id=?", (identifier,))
                result = {"id": identifier, "deleted": True}
            else:
                raise ValueError("未知素材操作")
            if action != "purge":
                result = self._public(db.execute("SELECT * FROM studio_library WHERE id=?", (identifier,)).fetchone())
        self.workspace.collect_unreferenced_assets(purge_assets)
        return result

    def clean_expired(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with self.workspace._connect() as db:
            return db.execute("DELETE FROM studio_library WHERE deleted_at IS NOT NULL AND deleted_at<=?", (cutoff,)).rowcount

    @staticmethod
    def _expired(value: str) -> bool:
        return datetime.fromisoformat(value) + timedelta(days=30) <= datetime.now(timezone.utc)

    @staticmethod
    def _public(row) -> dict:
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        result.pop("fingerprint")
        result["expires_at"] = (datetime.fromisoformat(result["deleted_at"]) + timedelta(days=30)).isoformat() if result["deleted_at"] else None
        return result
