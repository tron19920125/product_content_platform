from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from product_content_platform.adapters.layout_catalog import LayoutContentCatalog
from product_content_platform.domain import DomainValidationError


class LayoutContentCatalogTest(unittest.TestCase):
    def test_builtin_libraries_cover_square_landscape_and_portrait_ratios(self) -> None:
        catalog = LayoutContentCatalog()
        libraries = {item["id"]: item for item in catalog.libraries()}

        self.assertEqual("2048x2048", libraries["library-square-2048"]["size"])
        self.assertEqual("3840x2160", libraries["library-landscape-3840"]["size"])
        self.assertEqual("2160x3840", libraries["library-portrait-3840"]["size"])
        self.assertGreater(libraries["library-landscape-3840"]["width"], libraries["library-landscape-3840"]["height"])
        self.assertLess(libraries["library-portrait-3840"]["width"], libraries["library-portrait-3840"]["height"])

    def test_draft_geometry_is_versioned_and_published_versions_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = LayoutContentCatalog(Path(directory) / "templates.json")
            draft = catalog.create_template_draft(
                library_id="library-landscape-3840",
                name="测试横版",
                page_types=["hero"],
                title_box=[.05, .08, .34, .19],
                body_box=[.05, .22, .34, .36],
                product_box=[.40, .08, .96, .94],
                product_anchor_box=[.55, .18, .90, .90],
                safe_area_box=[.035, .06, .965, .94],
            )
            edited = catalog.update_template_draft(draft["id"], title_box=[.06, .09, .35, .20])
            published = catalog.publish_template(edited["id"])

            with self.assertRaises(DomainValidationError):
                catalog.update_template_draft(published["id"], name="禁止覆盖")

            next_version = catalog.create_next_version(published["id"])
            self.assertEqual(published["template_key"], next_version["template_key"])
            self.assertEqual(2, next_version["version"])
            self.assertEqual("draft", next_version["status"])
            self.assertNotEqual(published["id"], next_version["id"])
            catalog.delete_template_draft(next_version["id"])
            self.assertNotIn(
                next_version["id"],
                {item["id"] for item in catalog.templates(include_drafts=True)},
            )

    def test_legacy_flat_templates_are_migrated_to_a_size_library(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Path(directory) / "templates.json"
            storage.write_text(json.dumps([{
                "id": "legacy-wide",
                "name": "旧横版",
                "page_types": ["scene"],
                "layout": "overlay",
                "safe_area": .07,
                "text_box": [.05, .10, .35, .35],
                "product_box": [.40, .10, .95, .95],
                "product_anchor_box": [.52, .18, .90, .90],
                "composition_instruction": "旧构图",
                "scene_prompt_hint": "旧场景",
                "size": "3840x2160",
                "is_builtin": False,
            }], ensure_ascii=False), encoding="utf-8")

            catalog = LayoutContentCatalog(storage)
            migrated = catalog.template("legacy-wide")
            payload = json.loads(storage.read_text(encoding="utf-8"))

            self.assertEqual("library-landscape-3840", migrated["library_id"])
            self.assertEqual("3840x2160", migrated["size"])
            self.assertEqual(2, payload["schema_version"])

    def test_feature_slot_is_versioned_validated_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Path(directory) / "templates.json"
            catalog = LayoutContentCatalog(storage)
            draft = catalog.create_template_draft(
                library_id="library-landscape-3840",
                name="三联图文卖点",
                page_types=["selling_point"],
                feature_slots=[{
                    "id": "feature-band", "name": "三联卖点", "box": [.06, .58, .42, .88],
                    "layout": "row", "columns": 3, "min_items": 3, "max_items": 3,
                    "icon_position": "top",
                }],
            )
            self.assertEqual("feature-band", draft["feature_slots"][0]["id"])
            self.assertIn("后期叠加透明图标", draft["composition_instruction"])

            restored = LayoutContentCatalog(storage).template(draft["id"])
            self.assertEqual(3, restored["feature_slots"][0]["max_items"])

            with self.assertRaises(DomainValidationError):
                catalog.update_template_draft(
                    draft["id"],
                    feature_slots=[{"id": "bad", "box": [.02, .02, .20, .20], "min_items": 4, "max_items": 2}],
                )


if __name__ == "__main__":
    unittest.main()
