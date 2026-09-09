from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from product_content_platform.studio.catalog import DraftContent, Tool
from product_content_platform.studio.creations import Creations
from product_content_platform.studio.demo import DemoPack
from product_content_platform.studio.execution import package_job, package_review
from product_content_platform.studio.library import Library
from product_content_platform.studio.quality import Finding, Review, should_repair
from product_content_platform.studio.quality_tasks import QualityChecks
from product_content_platform.studio.settings import StudioSettings
from product_content_platform.studio.workspace import RevisionConflict, StudioWorkspace


def review(score):
    return Review(status="completed", product=float(score), layout=float(score), source="test-fixture")


class QualityTest(unittest.TestCase):
    def test_exact_repair_threshold_and_unknown_status(self):
        self.assertTrue(should_repair(review(59), repair_used=False))
        self.assertFalse(should_repair(review(60), repair_used=False))
        self.assertFalse(should_repair(review(20), repair_used=True))
        self.assertFalse(should_repair(review(20), repair_used=False, stopped=True))
        self.assertFalse(should_repair(Review(status="unavailable"), repair_used=False))
        self.assertIsNone(Review(status="checking", product=90.).score)

    def test_only_evidence_backed_critical_errors_cap_score(self):
        critical = Finding(kind="error", message="型号不符", evidence="底图标记 X，而参考为 Y", critical=True)
        result = Review(status="completed", product=96., layout=98., findings=[critical])
        self.assertEqual(59, result.score)
        uncertainty = Finding(kind="uncertain", message="反光较强，标签待核对")
        result = Review(status="completed", product=96., layout=98., findings=[uncertainty])
        self.assertGreater(result.score, 90)
        with self.assertRaises(ValueError):
            Finding(kind="suggestion", message="我不喜欢这个背景", critical=True)


class CreationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = StudioWorkspace(StudioSettings(Path(self.temporary.name)))
        self.creations = Creations(self.workspace)
        buffer = io.BytesIO()
        Image.new("RGB", (100, 100), "white").save(buffer, format="PNG")
        self.image = buffer.getvalue()
        self.product = self.workspace.upload_image("product.png", "product", self.image)
        self.output = self.workspace.upload_image("result.png", "style", self.image)
        draft = self.workspace.create_draft(Tool.MARKETING)
        draft["content"]["product_asset_ids"] = [self.product["id"]]
        self.draft = self.workspace.save_draft(draft["id"], DraftContent.model_validate(draft["content"]), expected_revision=1)
        self.page_id = self.draft["content"]["pages"][0]["id"]

    def tearDown(self):
        self.temporary.cleanup()

    def submit(self, key="one", **extra):
        return self.creations.submit(self.draft["id"], submit_key=key, expected_revision=self.draft["revision"], mode="demo", **extra)

    def finish(self, job, score=90):
        return self.creations.complete(job["id"], asset_id=self.output["id"], review=review(score), provenance={"provider": "test"})

    def test_idempotent_submit_and_conflicting_request_key(self):
        first = self.submit()
        self.assertEqual(first["id"], self.submit()["id"])
        with self.assertRaises(RevisionConflict):
            self.submit(instruction="different request")
        self.assertEqual(1, len(self.creations.snapshot(self.draft["id"])["operations"]))

    def test_history_distinguishes_waiting_from_actual_execution(self):
        self.submit()
        self.assertEqual("queued", self.creations.history()[0]["history_status"])
        job = self.creations.claim()
        self.assertEqual("processing", self.creations.history()[0]["history_status"])
        self.finish(job)
        self.assertEqual("completed", self.creations.history()[0]["history_status"])

    def test_unknown_result_is_not_hidden_by_another_queued_job(self):
        self.submit()
        self.creations.claim()
        self.creations.recover()
        self.submit(key="another")
        self.assertEqual("unknown", self.creations.history()[0]["history_status"])

    def test_incomplete_or_placeholder_fact_is_saved_but_never_generated(self):
        for facts in (
            [{"name": "容量", "value": "", "source": "规格书"}],
            [{"name": "容量", "value": "待填写", "source": "规格书"}],
        ):
            changed = {**self.draft["content"], "facts": facts}
            self.draft = self.workspace.save_draft(
                self.draft["id"], DraftContent.model_validate(changed),
                expected_revision=self.draft["revision"],
            )
            with self.assertRaisesRegex(ValueError, "尚未填写完整"):
                self.submit(str(self.draft["revision"]))

    def test_inflight_snapshot_does_not_follow_draft_changes(self):
        operation = self.submit()
        changed = {**self.draft["content"], "requirements": "后来修改的要求"}
        self.workspace.save_draft(self.draft["id"], DraftContent.model_validate(changed), expected_revision=2)
        job = self.creations.claim(operation["id"])
        self.assertEqual("", job["operation"]["snapshot"]["content"]["requirements"])

    def test_each_candidate_persists_even_if_next_one_fails(self):
        changed = {**self.draft["content"], "candidate_count": 2}
        self.draft = self.workspace.save_draft(self.draft["id"], DraftContent.model_validate(changed), expected_revision=2)
        operation = self.submit()
        first = self.creations.claim(operation["id"])
        finished = self.finish(first)
        second = self.creations.claim(operation["id"])
        self.creations.fail(second["id"], message="known failure", outcome_known=True)
        snapshot = self.creations.snapshot(self.draft["id"])
        self.assertEqual([finished["id"]], [value["id"] for value in snapshot["versions"]])
        self.creations.retry(second["id"])
        self.assertEqual(second["id"], self.creations.claim(operation["id"])["id"])
        with self.assertRaises(ValueError):
            self.creations.retry(first["id"])

    def test_provider_neutral_job_package_has_real_paths_and_no_invented_facts(self):
        operation = self.submit()
        job = self.creations.claim(operation["id"])
        package = package_job(job, self.workspace)
        self.assertTrue(Path(package["references"][0]["path"]).is_file())
        self.assertEqual("product", package["references"][0]["role"])
        self.assertEqual({"ratio": "1:1", "resolution": "2k", "width": 2048, "height": 2048, "quality": "high"}, package["requested_output"])
        self.assertIn("不得编造型号", package["prompt"])
        self.assertIn("未提供可引用的规格事实", package["prompt"])

    def test_completed_version_records_actual_and_requested_pixels_without_resizing(self):
        operation = self.submit()
        version = self.finish(self.creations.claim(operation["id"]))
        self.assertEqual((100, 100), (version["width"], version["height"]))
        self.assertEqual({"width": 100, "height": 100}, version["provenance"]["actual_output"])
        self.assertEqual((2048, 2048), (
            version["provenance"]["requested_output"]["width"],
            version["provenance"]["requested_output"]["height"],
        ))
        self.assertFalse(version["provenance"]["matches_requested_pixels"])

    def test_single_repair_survives_low_repair_and_repeated_result_delivery(self):
        operation = self.submit()
        first = self.creations.claim(operation["id"])
        version = self.finish(first, 40)
        same = self.finish(first, 40)
        self.assertEqual(version["id"], same["id"])
        repair = self.creations.claim(operation["id"])
        self.assertEqual("repair", repair["kind"])
        self.finish(repair, 50)
        self.assertIsNone(self.creations.claim(operation["id"]))
        snapshot = self.creations.snapshot(self.draft["id"])
        self.assertEqual(2, len(snapshot["versions"]))
        self.assertEqual(2, len(snapshot["operations"][0]["jobs"]))

    def test_repair_does_not_steal_user_selection(self):
        operation = self.submit()
        first = self.finish(self.creations.claim(operation["id"]), 40)
        self.creations.select(self.draft["id"], self.page_id, first["id"])
        fixed = self.finish(self.creations.claim(operation["id"]), 90)
        self.assertNotEqual(first["id"], fixed["id"])
        self.assertEqual(first["id"], self.creations.snapshot(self.draft["id"])["selections"][0]["version_id"])

    def test_higher_repair_is_selected_without_manual_intervention(self):
        operation = self.submit()
        self.finish(self.creations.claim(operation["id"]), 40)
        fixed = self.finish(self.creations.claim(operation["id"]), 90)
        self.assertEqual(fixed["id"], self.creations.snapshot(self.draft["id"])["selections"][0]["version_id"])

    def test_stop_keeps_inflight_result_without_dispatching_repair(self):
        operation = self.submit()
        job = self.creations.claim(operation["id"])
        self.creations.stop(operation["id"])
        self.finish(job, 40)
        self.assertIsNone(self.creations.claim(operation["id"]))
        self.assertEqual(1, len(self.creations.snapshot(self.draft["id"])["versions"]))

    def test_restart_marks_unknown_without_replay_and_can_accept_late_result(self):
        operation = self.submit()
        job = self.creations.claim(operation["id"])
        self.assertEqual(1, self.creations.recover())
        with self.assertRaises(ValueError):
            self.creations.retry(job["id"])
        self.assertIsNone(self.creations.claim(operation["id"]))
        self.finish(job)
        self.assertEqual(1, len(self.creations.snapshot(self.draft["id"])["versions"]))

    def test_history_delete_stops_queued_work_and_blocks_purge_while_inflight(self):
        operation = self.submit()
        job = self.creations.claim(operation["id"])
        trashed = self.creations.change_draft(self.draft["id"], action="trash")
        self.assertIsNotNone(trashed["deleted_at"])
        with self.assertRaisesRegex(ValueError, "在途"):
            self.creations.change_draft(self.draft["id"], action="purge")
        self.finish(job)
        result = self.creations.change_draft(self.draft["id"], action="purge")
        self.assertTrue(result["deleted"])
        with self.assertRaises(KeyError):
            self.workspace.get_draft(self.draft["id"])

    def test_quality_check_retries_twice_then_allows_manual_recheck_and_one_repair(self):
        operation = self.submit()
        job = self.creations.claim(operation["id"])
        version = self.creations.complete(
            job["id"], asset_id=self.output["id"], review=Review(status="unavailable"), provenance={"provider": "test"},
        )
        quality = QualityChecks(self.workspace, self.creations)
        task = quality.request(version["id"])
        for attempt in (1, 2):
            claimed = quality.claim()
            self.assertEqual(attempt, claimed["attempt"])
            failed = quality.fail(claimed["id"], message="temporary")
            self.assertEqual("queued", failed["status"])
        claimed = quality.claim()
        self.assertEqual(3, claimed["attempt"])
        self.assertEqual("failed", quality.fail(claimed["id"], message="still unavailable")["status"])
        self.assertIsNone(self.creations.get_version(version["id"])["review"]["score"])

        quality.request(version["id"])
        recheck = quality.claim()
        quality.complete(recheck["id"], review(40))
        repair = self.creations.claim(operation["id"])
        self.assertEqual("repair", repair["kind"])

    def test_quality_recheck_uses_the_generation_snapshot_not_later_draft_facts(self):
        operation = self.submit()
        job = self.creations.claim(operation["id"])
        version = self.creations.complete(
            job["id"], asset_id=self.output["id"], review=Review(status="unavailable"), provenance={"provider": "test"},
        )
        changed = {**self.draft["content"], "facts": [{"name": "容量", "value": "10 kg", "source": "后来上传的规格书"}]}
        self.draft = self.workspace.save_draft(
            self.draft["id"], DraftContent.model_validate(changed), expected_revision=self.draft["revision"],
        )
        checks = QualityChecks(self.workspace, self.creations)
        checks.request(version["id"])
        task = checks.claim()
        self.assertEqual([], package_review(task, self.workspace)["facts"])

    def test_manual_version_cannot_be_sent_to_quality_check(self):
        operation = self.submit()
        generated = self.finish(self.creations.claim(operation["id"]))
        edit = self.creations.save_edit(generated["id"], layers=[{"id": "text"}], expected_revision=0)
        manual = self.creations.apply_edit(generated["id"], expected_revision=edit["revision"], rendered_asset_id=self.output["id"])
        with self.assertRaisesRegex(ValueError, "手动编辑"):
            QualityChecks(self.workspace, self.creations).request(manual["id"])

    def test_editor_layers_are_normalized_and_reject_untrusted_image_references(self):
        operation = self.submit()
        generated = self.finish(self.creations.claim(operation["id"]))
        saved = self.creations.save_edit(generated["id"], layers=[{"id": "headline", "text": "标题"}], expected_revision=0)
        self.assertEqual("text", saved["layers"][0]["type"])
        self.assertEqual("StudioSans", saved["layers"][0]["font"])
        with self.assertRaisesRegex(ValueError, "图片图层"):
            self.creations.save_edit(
                generated["id"],
                layers=[{"id": "logo", "type": "image", "asset_id": self.product["id"], "image_url": "https://example.com/logo.png"}],
                expected_revision=saved["revision"],
            )
        with self.assertRaises(ValueError):
            self.creations.save_edit(generated["id"], layers=[{"id": "text", "unexpected": True}], expected_revision=saved["revision"])

    def test_parallel_claims_cannot_dispatch_a_job_twice(self):
        operation = self.submit()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.creations.claim(operation["id"]), range(4)))
        self.assertEqual(1, sum(value is not None for value in results))

    def test_manual_draft_apply_and_ai_edit_use_applied_layers_only(self):
        operation = self.submit()
        base = self.finish(self.creations.claim(operation["id"]))
        saved = self.creations.save_edit(base["id"], layers=[{"id": "applied", "text": "已应用文字"}], expected_revision=0)
        self.assertEqual(base["id"], self.creations.snapshot(self.draft["id"])["selections"][0]["version_id"])
        manual = self.creations.apply_edit(base["id"], expected_revision=saved["revision"], rendered_asset_id=self.output["id"])
        self.assertEqual("manual", manual["kind"])
        self.assertEqual("AI 底图评分", manual["score_label"])
        self.creations.save_edit(manual["id"], layers=[{"id": "not-applied", "text": "未应用草稿"}], expected_revision=0)
        edited_operation = self.submit("edit", page_ids=[self.page_id], source_version_id=manual["id"], instruction="背景暖一点")
        job = self.creations.claim(edited_operation["id"])
        self.assertEqual("applied", job["operation"]["snapshot"]["source_layers"][0]["id"])
        result = self.finish(job)
        self.assertEqual("applied", result["layers"][0]["id"])
        self.assertEqual(2, len(self.creations.snapshot(self.draft["id"])["operations"]))

    def test_library_snapshot_is_independent_and_deletion_protects_files(self):
        library = Library(self.workspace)
        referenced = {**self.draft["content"], "style_asset_ids": [self.output["id"]]}
        self.draft = self.workspace.save_draft(
            self.draft["id"], DraftContent.model_validate(referenced), expected_revision=self.draft["revision"],
        )
        original = {"asset_id": self.output["id"], "layers": [{"id": "first", "text": "最初"}]}
        entry = library.save(name="作品", kind="work", payload=original, asset_ids=[self.output["id"]])
        original["layers"][0]["text"] = "后来"
        self.assertEqual("最初", library.get(entry["id"])["payload"]["layers"][0]["text"])
        again = library.save(name="作品二", kind="work", payload=entry["payload"], asset_ids=[self.output["id"]])
        self.assertTrue(again["already_saved"])
        first_delete = library.change(entry["id"], action="trash")
        second_delete = library.change(entry["id"], action="trash")
        self.assertEqual(first_delete["expires_at"], second_delete["expires_at"])
        library.change(entry["id"], action="restore")
        self.assertEqual(1, len(library.list()))
        with self.assertRaises(ValueError):
            library.change(entry["id"], action="purge")
        library.change(entry["id"], action="trash")
        library.change(entry["id"], action="purge")
        self.assertTrue(self.workspace.asset_file(self.output["id"], preview=False)[0].exists())

        orphan = self.workspace.upload_image("orphan.png", "style", self.image)
        orphan_path = self.workspace.asset_file(orphan["id"], preview=False)[0]
        orphan_entry = library.save(name="可回收素材", kind="style", payload={"asset": orphan}, asset_ids=[orphan["id"]])
        library.change(orphan_entry["id"], action="trash")
        library.change(orphan_entry["id"], action="purge")
        self.assertFalse(orphan_path.exists())
        with self.assertRaises(KeyError):
            self.workspace.get_asset(orphan["id"])

    def test_continuing_saved_work_creates_independent_draft_and_versions_without_qa(self):
        operation = self.submit()
        generated = self.finish(self.creations.claim(operation["id"]))
        entry = Library(self.workspace).save(
            name="可编辑作品", kind="work",
            payload={"content": self.draft["content"], "versions": [generated]},
            asset_ids=[self.product["id"], self.output["id"]],
        )
        copied = self.creations.restore_work(entry)
        self.assertNotEqual(self.draft["id"], copied["draft"]["id"])
        self.assertNotEqual(generated["id"], copied["results"]["versions"][0]["id"])
        self.assertEqual(generated["review"]["score"], copied["results"]["versions"][0]["review"]["score"])
        self.assertEqual(generated["id"], copied["results"]["versions"][0]["provenance"]["copied_from"])
        edited = {**copied["draft"]["content"], "product_name": "副本中的新名称"}
        self.workspace.save_draft(copied["draft"]["id"], DraftContent.model_validate(edited), expected_revision=1)
        self.assertNotEqual("副本中的新名称", self.workspace.get_draft(self.draft["id"])["content"]["product_name"])


class DemoPackTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = StudioWorkspace(StudioSettings(Path(self.temporary.name)))
        self.creations = Creations(self.workspace)
        self.demo = DemoPack(self.workspace, self.creations)

    def tearDown(self):
        self.temporary.cleanup()

    def test_a_plus_replay_uses_only_the_matching_a_plus_set(self):
        draft = self.demo.create_draft(Tool.A_PLUS)
        operation = self.creations.submit(
            draft["id"], submit_key="a-plus-demo", expected_revision=draft["revision"], mode="demo",
        )
        self.demo.replay(operation["id"])
        snapshot = self.creations.snapshot(draft["id"])
        self.assertEqual(3, len(snapshot["versions"]))
        demo_ids = {version["provenance"]["demo_id"] for version in snapshot["versions"]}
        self.assertEqual(
            {"laundry-aplus-hero", "laundry-aplus-features", "laundry-aplus-scene"},
            demo_ids,
        )

    def test_changed_demo_request_is_rejected_instead_of_replaying_old_images(self):
        draft = self.demo.create_draft(Tool.MARKETING)
        changed = {**draft["content"], "requirements": "改成霍尔的夜景"}
        changed = self.workspace.save_draft(
            draft["id"], DraftContent.model_validate(changed), expected_revision=draft["revision"],
        )
        operation = self.creations.submit(
            changed["id"], submit_key="changed-demo", expected_revision=changed["revision"], mode="demo",
        )
        self.demo.replay(operation["id"])
        snapshot = self.creations.snapshot(changed["id"])
        self.assertFalse(snapshot["versions"])
        self.assertEqual("failed", snapshot["operations"][0]["jobs"][0]["status"])
        self.assertIn("示例输入已改动", snapshot["operations"][0]["jobs"][0]["error"])

    def test_blank_a_plus_modules_cannot_skip_planning(self):
        draft = self.workspace.create_draft(Tool.A_PLUS)
        reference = self.demo.file(self.demo.manifest()["reference"]["file"])
        asset = self.workspace.upload_image(reference.name, "product", reference.read_bytes())
        draft["content"]["product_asset_ids"] = [asset["id"]]
        draft = self.workspace.save_draft(
            draft["id"], DraftContent.model_validate(draft["content"]), expected_revision=draft["revision"],
        )
        with self.assertRaisesRegex(ValueError, r"先生成 A\+ 模块方案"):
            self.creations.submit(
                draft["id"], submit_key="blank-a-plus", expected_revision=draft["revision"], mode="codex",
            )


if __name__ == "__main__":
    unittest.main()
