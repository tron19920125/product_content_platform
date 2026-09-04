from __future__ import annotations

import io
import json
import sqlite3
import warnings
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from .catalog import AssetUsage, DraftContent, Tool, default_draft
from .settings import StudioSettings


class RevisionConflict(Exception):
    """An autosave may not overwrite a newer saved draft."""


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class StudioWorkspace:
    """Owns durable draft and reference input operations for all five tools.

    No project, template, approval or model invocation is required at this seam.
    Each update is conditional on the revision the caller actually edited.
    """

    def __init__(self, settings: StudioSettings) -> None:
        self.settings = settings
        settings.initialize()
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS studio_assets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    usage TEXT NOT NULL CHECK (usage IN ('product', 'style', 'logo')),
                    source_file TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    byte_count INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS studio_drafts (
                    id TEXT PRIMARY KEY,
                    tool TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS studio_drafts_by_tool
                    ON studio_drafts (tool, updated_at DESC);
                CREATE TABLE IF NOT EXISTS studio_draft_assets (
                    draft_id TEXT NOT NULL REFERENCES studio_drafts(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES studio_assets(id),
                    PRIMARY KEY (draft_id, asset_id)
                );
                CREATE TABLE IF NOT EXISTS studio_plan_versions (
                    id TEXT PRIMARY KEY,
                    draft_id TEXT NOT NULL REFERENCES studio_drafts(id) ON DELETE CASCADE,
                    label TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS studio_plans_by_draft
                    ON studio_plan_versions (draft_id, created_at DESC);
                PRAGMA user_version=1;
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(studio_drafts)")}
            if "deleted_at" not in columns:
                db.execute("ALTER TABLE studio_drafts ADD COLUMN deleted_at TEXT")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.settings.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_draft(self, tool: Tool) -> dict:
        identifier, now = str(uuid4()), timestamp()
        content = default_draft(tool)
        with self._connect() as db:
            db.execute("""INSERT INTO studio_drafts
                (id, tool, revision, content, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL)""",
                (identifier, tool.value, 1, content.model_dump_json(), now, now))
            return self._draft(db.execute("SELECT * FROM studio_drafts WHERE id=?", (identifier,)).fetchone())

    def get_draft(self, identifier: str) -> dict:
        with self._connect() as db:
            return self._draft(self._find(db, "studio_drafts", identifier))

    def list_drafts(self, tool: Tool | None = None, *, trash: bool = False) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM studio_drafts
                   WHERE (? IS NULL OR tool=?) AND ((deleted_at IS NOT NULL)=?)
                   ORDER BY updated_at DESC, id""",
                (tool.value if tool else None, tool.value if tool else None, int(trash)),
            ).fetchall()
            return [self._draft(row) for row in rows]

    def save_draft(self, identifier: str, content: DraftContent, *, expected_revision: int) -> dict:
        references = [(value, "product") for value in content.product_asset_ids]
        references += [(value, "style") for value in content.style_asset_ids]
        if content.logo_asset_id:
            references.append((content.logo_asset_id, "logo"))
        if len(references) > self.settings.max_references:
            raise ValueError(f"当前配置最多接受 {self.settings.max_references} 张参考图（含 Logo），请移除多余图片")
        with self._connect() as db:
            # Serializes revision checks and reference validation with the write.
            db.execute("BEGIN IMMEDIATE")
            old = self._find(db, "studio_drafts", identifier)
            if old["revision"] != expected_revision:
                raise RevisionConflict("草稿已在其他页面更新，请重新加载后再保存")
            if old["tool"] != content.tool.value:
                raise ValueError("不能将当前草稿改为另一工具，请显式新建或复用")
            for asset_id, usage in references:
                asset = db.execute("SELECT usage FROM studio_assets WHERE id=?", (asset_id,)).fetchone()
                if asset is None:
                    raise ValueError("引用的素材不存在，请重新选择")
                if asset["usage"] != usage:
                    raise ValueError("商品图、风格参考与 Logo 用途必须匹配，不能互相替代")
            changed = db.execute(
                "UPDATE studio_drafts SET revision=revision+1, content=?, updated_at=? WHERE id=? AND revision=?",
                (content.model_dump_json(), timestamp(), identifier, expected_revision),
            )
            if changed.rowcount != 1:
                raise RevisionConflict("草稿版本冲突，请重新加载")
            db.execute("DELETE FROM studio_draft_assets WHERE draft_id=?", (identifier,))
            db.executemany(
                "INSERT INTO studio_draft_assets VALUES (?, ?)",
                [(identifier, asset_id) for asset_id, _ in references],
            )
            return self._draft(self._find(db, "studio_drafts", identifier))

    def upload_image(self, name: str, usage: AssetUsage, content: bytes) -> dict:
        if usage not in {"product", "style", "logo"}:
            raise ValueError("素材用途无效")
        name = Path(name.replace("\\", "/")).name.strip()
        suffix = Path(name).suffix.lower()
        formats = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
        if not name or len(name) > 240 or suffix not in formats:
            raise ValueError("仅支持 PNG、JPG、WebP 图片，文件名最长 240 字符")
        if not content or len(content) > self.settings.max_upload_bytes:
            raise ValueError(f"图片不能为空，且不能超过 {self.settings.max_upload_bytes} 字节")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as original:
                    if original.format != formats[suffix]:
                        raise ValueError("图片内容与扩展名不一致")
                    if original.width * original.height > 50_000_000:
                        raise ValueError("图片像素过大，最多支持 5000 万像素")
                    if getattr(original, "n_frames", 1) != 1:
                        raise ValueError("请上传静态图片，不支持动画")
                    original.verify()
                with Image.open(io.BytesIO(content)) as original:
                    original.load()
                    oriented = ImageOps.exif_transpose(original)
                    width, height = oriented.size
                    preview = oriented.convert("RGBA")
                    preview.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
                    # The downloadable source is unchanged; public previews carry
                    # no source EXIF/GPS. Full-size model inputs are a later stage.
                    preview.info.clear()
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as exc:
            raise ValueError("图片损坏或不能安全解码，请换一张图片") from exc

        identifier = str(uuid4())
        directory = self.settings.data_root / "assets" / identifier
        directory.mkdir()
        source_file = "source" + suffix
        source_path, preview_path = directory / source_file, directory / "preview.png"
        media_type = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[formats[suffix]]
        try:
            source_path.write_bytes(content)
            preview.save(preview_path, format="PNG")
            with self._connect() as db:
                db.execute(
                    "INSERT INTO studio_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (identifier, name, usage, source_file, media_type, len(content), width, height, timestamp()),
                )
        except Exception:
            # Only these newly-created files belong to this failed upload.
            preview_path.unlink(missing_ok=True)
            source_path.unlink(missing_ok=True)
            directory.rmdir()
            raise
        return self.get_asset(identifier)

    def record_plan(self, draft_id: str, content: DraftContent, *, label: str) -> dict:
        if content.tool != Tool.A_PLUS:
            raise ValueError("只有 A+ 详情图使用模块方案版本")
        if not label.strip() or len(label) > 100:
            raise ValueError("方案版本名称无效")
        identifier, now = str(uuid4()), timestamp()
        with self._connect() as db:
            draft = self._find(db, "studio_drafts", draft_id)
            if draft["tool"] != Tool.A_PLUS.value:
                raise ValueError("当前记录不是 A+ 详情图")
            db.execute("INSERT INTO studio_plan_versions VALUES (?, ?, ?, ?, ?)",
                       (identifier, draft_id, label.strip(), content.model_dump_json(), now))
        return {"id": identifier, "draft_id": draft_id, "label": label.strip(), "content": content.model_dump(mode="json"), "created_at": now}

    def list_plans(self, draft_id: str) -> list[dict]:
        with self._connect() as db:
            self._find(db, "studio_drafts", draft_id)
            rows = db.execute("SELECT * FROM studio_plan_versions WHERE draft_id=? ORDER BY created_at DESC, id DESC", (draft_id,)).fetchall()
        return [{**dict(row), "content": json.loads(row["content"])} for row in rows]

    def restore_plan(self, draft_id: str, plan_id: str, *, expected_revision: int) -> dict:
        current = self.get_draft(draft_id)
        if current["revision"] != expected_revision:
            raise RevisionConflict("输入已变化，请重新打开方案历史")
        with self._connect() as db:
            row = db.execute("SELECT * FROM studio_plan_versions WHERE id=? AND draft_id=?", (plan_id, draft_id)).fetchone()
            if not row:
                raise KeyError("方案版本不存在")
            restored = DraftContent.model_validate_json(row["content"])
        current_content = DraftContent.model_validate(current["content"])
        self.record_plan(draft_id, current_content, label="恢复前的当前方案")
        saved = self.save_draft(draft_id, restored, expected_revision=expected_revision)
        self.record_plan(draft_id, restored, label=f"已恢复：{row['label']}")
        return saved

    def get_asset(self, identifier: str) -> dict:
        with self._connect() as db:
            row = dict(self._find(db, "studio_assets", identifier))
        row.pop("source_file")
        row["preview_url"] = f"/api/studio/assets/{identifier}/preview"
        row["source_url"] = f"/api/studio/assets/{identifier}/source"
        # Uploading into a draft does not publish it into the future asset library.
        row["in_library"] = False
        return row

    def asset_file(self, identifier: str, *, preview: bool) -> tuple[Path, str]:
        with self._connect() as db:
            row = self._find(db, "studio_assets", identifier)
        root = (self.settings.data_root / "assets").resolve()
        path = (root / identifier / ("preview.png" if preview else row["source_file"])).resolve()
        if root not in path.parents or not path.is_file():
            raise KeyError("素材文件不存在")
        return path, "image/png" if preview else row["media_type"]

    def collect_unreferenced_assets(self, candidates: set[str]) -> int:
        """Delete only explicitly nominated files that no live record still uses."""
        if not candidates:
            return 0
        removable: list[tuple[str, str]] = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            layer_references: set[str] = set()
            for table in ("studio_versions", "studio_edit_drafts"):
                if table in tables:
                    for row in db.execute(f"SELECT layers FROM {table}"):
                        try:
                            layer_references.update(
                                layer["asset_id"] for layer in json.loads(row[0])
                                if isinstance(layer, dict) and isinstance(layer.get("asset_id"), str)
                            )
                        except (json.JSONDecodeError, TypeError):
                            # Corrupt retained metadata is not a reason to delete files.
                            return 0
            for identifier in candidates:
                row = db.execute("SELECT source_file FROM studio_assets WHERE id=?", (identifier,)).fetchone()
                if not row or identifier in layer_references:
                    continue
                references = 0
                for table in ("studio_draft_assets", "studio_operation_assets", "studio_library_assets"):
                    if table in tables:
                        references += db.execute(f"SELECT COUNT(*) FROM {table} WHERE asset_id=?", (identifier,)).fetchone()[0]
                if "studio_versions" in tables:
                    references += db.execute(
                        "SELECT COUNT(*) FROM studio_versions WHERE base_asset_id=? OR render_asset_id=?",
                        (identifier, identifier),
                    ).fetchone()[0]
                if not references:
                    db.execute("DELETE FROM studio_assets WHERE id=?", (identifier,))
                    removable.append((identifier, row["source_file"]))

        root = (self.settings.data_root / "assets").resolve()
        removed = 0
        for identifier, source_file in removable:
            directory = (root / identifier).resolve()
            if directory.parent != root or not directory.is_dir() or directory.is_symlink():
                continue
            (directory / source_file).unlink(missing_ok=True)
            (directory / "preview.png").unlink(missing_ok=True)
            try:
                directory.rmdir()
            except OSError:
                # Unknown files are preserved for manual inspection.
                continue
            removed += 1
        return removed

    @staticmethod
    def _find(db: sqlite3.Connection, table: str, identifier: str) -> sqlite3.Row:
        # Table names are internal constants, never request input.
        if table not in {"studio_drafts", "studio_assets"}:
            raise ValueError("未知数据表")
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError("记录不存在")
        return row

    @staticmethod
    def _draft(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["content"] = json.loads(result["content"])
        result["expires_at"] = (
            (datetime.fromisoformat(result["deleted_at"]) + timedelta(days=30)).isoformat()
            if result.get("deleted_at") else None
        )
        return result
