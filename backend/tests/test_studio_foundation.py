from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from product_content_platform.studio.api import create_app
from product_content_platform.studio.catalog import (
    DraftContent, IMAGE_SIZES, OutputSettings, PageDraft, Tool, default_draft,
)
from product_content_platform.studio.settings import StudioSettings
from product_content_platform.studio.workspace import RevisionConflict, StudioWorkspace


def image_bytes(format: str = "PNG", *, exif=None) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 40), "#635bff").save(output, format=format, **({"exif": exif} if exif else {}))
    return output.getvalue()


class StudioCatalogTest(unittest.TestCase):
    def test_defaults_do_not_require_a_project_or_seed_product_facts(self):
        for tool in Tool:
            draft = default_draft(tool)
            self.assertEqual("", draft.product_name)
            self.assertEqual("", draft.sku)
            self.assertEqual("", draft.category)
            self.assertEqual([], draft.facts)
            self.assertEqual(1, draft.candidate_count)
            self.assertEqual("2k", draft.output.resolution)
            self.assertNotIn("template_id", draft.model_dump())
        self.assertEqual(3, len(default_draft(Tool.ECOM_SUITE).pages))
        self.assertEqual(3, len(default_draft(Tool.A_PLUS).pages))
        self.assertEqual("amazon_en", default_draft(Tool.A_PLUS).market)
        self.assertEqual("16:9", default_draft(Tool.A_PLUS).output.ratio)
        self.assertEqual("background_only", default_draft(Tool.SCENE).text_mode)
        self.assertEqual("3:4", default_draft(Tool.SCENE).output.ratio)

    def test_four_candidates_and_exact_application_sizes(self):
        self.assertEqual(14, sum(len(levels) for levels in IMAGE_SIZES.values()))
        for ratio, levels in IMAGE_SIZES.items():
            for level, (width, height) in levels.items():
                output = OutputSettings(ratio=ratio, resolution=level)
                self.assertEqual((width, height), output.pixels)
                self.assertEqual(0, width % 16)
                self.assertEqual(0, height % 16)
        for count in [1, 2, 4]:
            self.assertEqual(count, DraftContent(tool=Tool.MARKETING, candidate_count=count).candidate_count)
        for invalid in [0, 3, 5, "4", True, 4.0]:
            with self.assertRaises(ValidationError):
                DraftContent(tool=Tool.MARKETING, candidate_count=invalid)
        with self.assertRaises(ValidationError):
            OutputSettings(ratio="5:4")

    def test_page_limits_purposes_and_stable_ids(self):
        for tool, count, purpose in [(Tool.ECOM_SUITE, 15, "scene"), (Tool.A_PLUS, 6, "hero"), (Tool.SCENE, 1, "scene")]:
            pages = [PageDraft(purpose=purpose) for _ in range(count)]
            draft = DraftContent(tool=tool, pages=pages)
            reversed_data = draft.model_dump(mode="json")
            reversed_data["pages"].reverse()
            reordered = DraftContent.model_validate(reversed_data)
            self.assertEqual([page.id for page in reversed(pages)], [page.id for page in reordered.pages])
            with self.assertRaises(ValidationError):
                DraftContent(tool=tool, pages=pages + [PageDraft(purpose=purpose)])
        page = PageDraft(purpose="scene")
        with self.assertRaises(ValidationError):
            DraftContent(tool=Tool.ECOM_SUITE, pages=[page, page])
        with self.assertRaises(ValidationError):
            DraftContent(tool=Tool.SCENE, pages=[PageDraft(purpose="marketing")])

    def test_defaults_are_independent_and_incomplete_drafts_are_allowed(self):
        first, second = default_draft(Tool.A_PLUS), default_draft(Tool.A_PLUS)
        self.assertNotEqual(first.pages[0].id, second.pages[0].id)
        first.pages.pop()
        self.assertEqual(3, len(second.pages))
        self.assertEqual([], DraftContent(tool=Tool.MARKETING).pages)

    def test_asset_roles_are_unambiguous_and_incomplete_facts_are_draftable(self):
        with self.assertRaises(ValidationError):
            DraftContent(tool=Tool.SCENE, product_asset_ids=["one"], style_asset_ids=["one"])
        draft = DraftContent(tool=Tool.SCENE, facts=[{"name": "容量", "value": "12L", "source": " "}])
        with self.assertRaisesRegex(ValueError, "尚未填写完整"):
            draft.facts[0].validate_for_generation()
        with self.assertRaises(ValidationError):
            DraftContent(tool=Tool.SCENE, template_id="legacy")


class StudioApiTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "new-workspace"
        self.settings = StudioSettings(self.root)
        self.client = TestClient(create_app(self.settings))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temporary.cleanup()

    def upload(self, usage="product", name="product.png", content=None):
        response = self.client.post(
            "/api/studio/assets", params={"filename": name, "usage": usage},
            content=image_bytes() if content is None else content,
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def draft(self, tool="scene_image"):
        response = self.client.post("/api/studio/drafts", json={"tool": tool})
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def save(self, draft):
        return self.client.put(f"/api/studio/drafts/{draft['id']}", json={
            "expected_revision": draft["revision"], "content": draft["content"],
        })

    def test_startup_has_no_fake_history_legacy_tables_or_generated_results(self):
        health = self.client.get("/api/health").json()
        self.assertEqual("studio", health["workspace"])
        self.assertFalse(health["generation_available"])
        self.assertEqual([], self.client.get("/api/studio/drafts").json())
        self.assertFalse((self.root / "platform.db").exists())
        for name in ["production", "exports", "fonts", "cache", "logs", "run"]:
            self.assertEqual([], list((self.root / name).iterdir()))
        self.assertEqual(404, self.client.get("/api/projects").status_code)

    def test_catalog_exposes_limits_not_a_fake_deployment_guarantee(self):
        response = self.client.get("/api/studio/catalog")
        self.assertEqual(200, response.status_code, response.text)
        value = response.json()
        self.assertEqual(5, len(value["tools"]))
        self.assertEqual(14, len(value["sizes"]))
        self.assertEqual([1, 2, 4], value["candidate_counts"])
        self.assertEqual("high", value["quality"])
        self.assertEqual(6, value["limits"]["total_references"])
        self.assertEqual("pending", value["deployment_validation"])
        self.assertFalse(value["generation_available"])

    def test_upload_preserves_source_and_exposes_preview_without_local_paths(self):
        content = image_bytes()
        asset = self.upload(name="../product.png", content=content)
        self.assertEqual("product.png", asset["name"])
        self.assertEqual((80, 40), (asset["width"], asset["height"]))
        self.assertFalse(asset["in_library"])
        self.assertNotIn("source_file", asset)
        self.assertNotIn(str(self.root), str(asset))
        self.assertEqual(content, self.client.get(asset["source_url"]).content)
        with Image.open(io.BytesIO(self.client.get(asset["preview_url"]).content)) as preview:
            self.assertEqual((80, 40), preview.size)

    def test_exif_orientation_is_corrected_in_preview_but_source_is_preserved(self):
        exif = Image.Exif()
        exif[274] = 6
        content = image_bytes("JPEG", exif=exif)
        asset = self.upload(name="rotated.jpg", content=content)
        self.assertEqual((40, 80), (asset["width"], asset["height"]))
        self.assertEqual(content, self.client.get(asset["source_url"]).content)
        with Image.open(io.BytesIO(self.client.get(asset["preview_url"]).content)) as image:
            self.assertEqual((40, 80), image.size)
            self.assertFalse(image.getexif())

    def test_bad_uploads_do_not_write_assets(self):
        for name, content, usage in [
            ("wrong.jpg", image_bytes(), "product"), ("book.pdf", b"%PDF-1.0", "product"),
            ("bad.png", b"not-an-image", "product"), ("empty.png", b"", "product"),
            ("product.png", image_bytes(), "unknown"),
        ]:
            response = self.client.post("/api/studio/assets", params={"filename": name, "usage": usage}, content=content)
            self.assertEqual(422, response.status_code, response.text)
        self.assertEqual([], list((self.root / "assets").iterdir()))

    def test_upload_byte_limit_is_enforced_while_streaming(self):
        settings = StudioSettings(Path(self.temporary.name) / "small-limit", max_upload_bytes=64)
        with TestClient(create_app(settings)) as client:
            response = client.post("/api/studio/assets", params={"filename": "large.png", "usage": "product"}, content=image_bytes())
            self.assertEqual(413, response.status_code)
            self.assertEqual([], list((settings.data_root / "assets").iterdir()))

    def test_save_restore_and_tool_filter_do_not_mix_product_facts(self):
        asset, draft = self.upload(), self.draft()
        draft["content"]["product_asset_ids"] = [asset["id"]]
        draft["content"]["product_name"] = "用户商品"
        saved = self.save(draft)
        self.assertEqual(200, saved.status_code, saved.text)
        self.assertEqual(2, saved.json()["revision"])
        other = self.draft("marketing_main_image")
        self.assertEqual("", other["content"]["product_name"])
        listed = self.client.get("/api/studio/drafts", params={"tool": "scene_image"}).json()
        self.assertEqual([draft["id"]], [value["id"] for value in listed])
        with TestClient(create_app(self.settings)) as reopened:
            restored = reopened.get(f"/api/studio/drafts/{draft['id']}").json()
            self.assertEqual(saved.json(), restored)
            self.assertEqual(200, reopened.get(asset["source_url"]).status_code)

    def test_stale_save_is_conflict_not_last_writer_wins(self):
        draft = self.draft()
        draft["content"]["requirements"] = "第一版"
        self.assertEqual(200, self.save(draft).status_code)
        draft["content"]["requirements"] = "过期页面的版本"
        self.assertEqual(409, self.save(draft).status_code)
        restored = self.client.get(f"/api/studio/drafts/{draft['id']}").json()
        self.assertEqual("第一版", restored["content"]["requirements"])

    def test_history_has_an_independent_30_day_recycle_bin(self):
        draft = self.draft()
        trashed = self.client.post(f"/api/studio/drafts/{draft['id']}/lifecycle", json={"action": "trash"})
        self.assertEqual(200, trashed.status_code, trashed.text)
        self.assertIsNotNone(trashed.json()["expires_at"])
        self.assertEqual([], self.client.get("/api/studio/drafts").json())
        self.assertEqual([draft["id"]], [row["id"] for row in self.client.get("/api/studio/drafts", params={"trash": True}).json()])
        restored = self.client.post(f"/api/studio/drafts/{draft['id']}/lifecycle", json={"action": "restore"})
        self.assertEqual(200, restored.status_code, restored.text)
        self.assertIsNone(restored.json()["deleted_at"])
        self.client.post(f"/api/studio/drafts/{draft['id']}/lifecycle", json={"action": "trash"})
        purged = self.client.post(f"/api/studio/drafts/{draft['id']}/lifecycle", json={"action": "purge"})
        self.assertEqual({"id": draft["id"], "deleted": True}, purged.json())
        self.assertEqual(404, self.client.get(f"/api/studio/drafts/{draft['id']}").status_code)

    def test_parallel_saves_have_one_winner(self):
        draft = self.draft()
        workspace = StudioWorkspace(self.settings)

        def save_version(value):
            content = DraftContent.model_validate({**draft["content"], "requirements": value})
            try:
                return workspace.save_draft(draft["id"], content, expected_revision=1)["revision"]
            except RevisionConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save_version, ["一", "二"]))
        self.assertCountEqual([2, "conflict"], results)

    def test_asset_validation_is_atomic_and_rejects_role_substitution(self):
        style, draft = self.upload("style"), self.draft()
        for identifier in ["missing-asset", style["id"]]:
            draft["content"]["product_asset_ids"] = [identifier]
            self.assertEqual(422, self.save(draft).status_code)
            self.assertEqual(1, self.client.get(f"/api/studio/drafts/{draft['id']}").json()["revision"])
        draft["content"]["product_asset_ids"] = []
        draft["content"]["style_asset_ids"] = [style["id"]]
        self.assertEqual(200, self.save(draft).status_code)

    def test_reference_total_is_not_silently_truncated(self):
        draft = self.draft()
        products = [self.upload()["id"] for _ in range(6)]
        draft["content"]["product_asset_ids"] = products
        draft["content"]["style_asset_ids"] = [self.upload("style")["id"]]
        result = self.save(draft)
        self.assertEqual(422, result.status_code)
        self.assertIn("6", result.json()["detail"])
        self.assertEqual([], self.client.get(f"/api/studio/drafts/{draft['id']}").json()["content"]["product_asset_ids"])

    def test_tool_cannot_change_in_place_and_unknown_fields_are_rejected(self):
        draft = self.draft()
        draft["content"] = default_draft(Tool.MARKETING).model_dump(mode="json")
        self.assertEqual(422, self.save(draft).status_code)
        response = self.client.post("/api/studio/drafts", json={"tool": "scene_image", "project_id": "old"})
        self.assertEqual(422, response.status_code)
        self.assertEqual(404, self.client.get("/api/studio/drafts/missing").status_code)

    def test_asset_symlink_cannot_serve_files_outside_assets(self):
        asset = self.upload()
        source = self.root / "assets" / asset["id"] / "source.png"
        source.unlink()
        outside = Path(self.temporary.name) / "outside.png"
        outside.write_bytes(image_bytes())
        source.symlink_to(outside)
        self.assertEqual(404, self.client.get(asset["source_url"]).status_code)


class StudioIsolationTest(unittest.TestCase):
    def test_environment_does_not_inherit_legacy_data_root(self):
        with patch.dict(os.environ, {"PCP_DATA_ROOT": "/tmp/legacy-product-data"}, clear=True):
            settings = StudioSettings.from_environment()
            self.assertEqual("data-refactor", settings.data_root.name)
            self.assertNotEqual(Path("/tmp/legacy-product-data"), settings.data_root)

    def test_refuses_old_database_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "platform.db"
            old.write_bytes(b"old database sentinel")
            with self.assertRaisesRegex(ValueError, "旧数据目录"):
                StudioWorkspace(StudioSettings(root))
            self.assertEqual(b"old database sentinel", old.read_bytes())
            self.assertEqual(["platform.db"], [path.name for path in root.iterdir()])

    def test_creating_app_does_not_initialize_database_until_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "not-started"
            create_app(StudioSettings(root))
            self.assertFalse(root.exists())

    def test_bad_reference_configuration_is_rejected(self):
        for limit in [0, 17]:
            with self.assertRaises(ValueError):
                StudioSettings(Path("/tmp/not-created"), max_references=limit)

    def test_workspace_subdirectory_cannot_redirect_into_old_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "new"
            old = Path(directory) / "old"
            root.mkdir()
            old.mkdir()
            (root / "assets").symlink_to(old, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "符号链接"):
                StudioWorkspace(StudioSettings(root))
            self.assertEqual([], list(old.iterdir()))

    def test_check_command_has_no_write_or_legacy_startup_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "not-started"
            result = subprocess.run(
                [sys.executable, "-m", "product_content_platform.studio", "--check"],
                env={**os.environ, "PCP_STUDIO_DATA_ROOT": str(root), "PCP_GENERATION_MODE": "azure"},
                capture_output=True, text=True, check=True,
            )
            self.assertIn('"generation_available": false', result.stdout)
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
