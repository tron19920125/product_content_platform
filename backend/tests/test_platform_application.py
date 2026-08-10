from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from product_content_platform.adapters import SQLitePlatformRepository
from product_content_platform.application import BatchSkuInput, PlatformApplication, ProjectInput
from product_content_platform.domain import (
    AssetUsage,
    BatchItemStatus,
    BatchStatus,
    DomainValidationError,
    ProductProfile,
    ProjectStatus,
)


def profile(sku: str) -> ProductProfile:
    return ProductProfile(
        sku=sku,
        name=f"测试商品 {sku}",
        category="洗衣机",
        model=sku,
        selling_points=("低温柔洗", "智能投放"),
        parameters={"容量": "12kg"},
    )


class PlatformApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        repository = SQLitePlatformRepository(Path(self.temp_dir.name) / "platform.db")
        self.platform = PlatformApplication(repository)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_and_reload_project(self) -> None:
        created = self.platform.create_project(ProjectInput("X11详情页", profile("X11")))

        loaded = self.platform.get_project(created.id)

        self.assertEqual("X11详情页", loaded.name)
        self.assertEqual("X11", loaded.profile.sku)
        self.assertEqual({"容量": "12kg"}, loaded.profile.parameters)

    def test_create_batch_creates_one_project_per_sku(self) -> None:
        batch = self.platform.create_batch(
            "洗护批次",
            [BatchSkuInput(profile("X11")), BatchSkuInput(profile("T1"))],
            {"recipe_id": "recipe-hero"},
        )

        self.assertEqual(BatchStatus.READY, batch.status)
        self.assertEqual(2, batch.progress["total"])
        self.assertEqual(2, len(self.platform.list_projects()))
        self.assertEqual({"X11", "T1"}, {item.sku for item in batch.items})

    def test_duplicate_sku_is_rejected_before_persistence(self) -> None:
        with self.assertRaisesRegex(DomainValidationError, "重复SKU"):
            self.platform.create_batch(
                "重复批次",
                [BatchSkuInput(profile("X11")), BatchSkuInput(profile("X11"))],
            )

        self.assertEqual([], self.platform.list_batches())
        self.assertEqual([], self.platform.list_projects())

    def test_batch_failure_is_isolated_and_aggregate_status_is_updated(self) -> None:
        batch = self.platform.create_batch(
            "失败隔离",
            [BatchSkuInput(profile("X11")), BatchSkuInput(profile("T1"))],
        )

        updated = self.platform.set_batch_item_status(
            batch.id,
            batch.items[0].id,
            BatchItemStatus.FAILED,
            "生成超时",
        )

        self.assertEqual(BatchStatus.PARTIAL_FAILED, updated.status)
        self.assertEqual("生成超时", updated.items[0].error)
        self.assertEqual(BatchItemStatus.PENDING, updated.items[1].status)

    def test_asset_registration_updates_product_profile(self) -> None:
        project = self.platform.create_project(ProjectInput("X11详情页", profile("X11")))

        asset = self.platform.register_asset(
            project.id,
            AssetUsage.PRODUCT,
            "front.png",
            "image/png",
            "stored/front.png",
            128,
        )

        self.assertEqual([asset], self.platform.list_assets(project.id))
        self.assertEqual((asset.id,), self.platform.get_project(project.id).profile.reference_assets)

    def test_generate_edit_and_confirm_page_plan(self) -> None:
        project = self.platform.create_project(ProjectInput("X11详情页", profile("X11")))

        generated = self.platform.generate_plan(project.id)
        edited_items = list(generated.items)
        edited_items[0] = replace(edited_items[0], title="X11 全新主视觉")
        confirmed = self.platform.save_plan(project.id, edited_items, confirmed=True)

        self.assertEqual(5, len(generated.items))
        self.assertEqual(2, confirmed.version)
        self.assertTrue(confirmed.confirmed)
        self.assertEqual("X11 全新主视觉", confirmed.items[0].title)
        self.assertEqual("planned", self.platform.get_project(project.id).status.value)

    def test_regenerating_or_saving_draft_resets_project_to_draft(self) -> None:
        project = self.platform.create_project(ProjectInput("X11详情页", profile("X11")))
        self.platform.set_project_status(project.id, ProjectStatus.REVIEWING)

        generated = self.platform.generate_plan(project.id)

        self.assertFalse(generated.confirmed)
        self.assertEqual(ProjectStatus.DRAFT, self.platform.get_project(project.id).status)

        self.platform.set_project_status(project.id, ProjectStatus.REVIEWING)
        self.platform.save_plan(project.id, generated.items, confirmed=False)

        self.assertEqual(ProjectStatus.DRAFT, self.platform.get_project(project.id).status)


if __name__ == "__main__":
    unittest.main()
