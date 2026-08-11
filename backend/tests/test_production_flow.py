from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from product_content_platform.api import create_app
from product_content_platform.domain import JobStatus


class ProductionFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.client = TestClient(
            create_app(
                database_path=root / "platform.db",
                asset_root=root / "assets",
                production_root=root / "production",
                export_root=root / "exports",
            )
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def _create_planned_project(self) -> str:
        response = self.client.post(
            "/api/projects",
            json={
                "project_name": "X11完整生产",
                "profile": {
                    "sku": "X11",
                    "name": "COLMO X11洗衣机",
                    "category": "洗衣机",
                    "model": "CGU12W-X11",
                    "selling_points": ["AI轻干洗2.0", "智能护理"],
                    "parameters": {"容量": "12kg", "洗净比": "1.1"},
                    "reference_assets": [],
                    "brand_requirements": "",
                    "output_requirements": "电商详情页",
                },
            },
        )
        project_id = response.json()["id"]
        image = Image.new("RGB", (500, 700), "white")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((100, 70, 400, 640), 28, fill="#d8ded9", outline="#58665d", width=8)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        uploaded = self.client.post(
            f"/api/projects/{project_id}/assets?file_name=x11.png&usage=product",
            content=buffer.getvalue(),
            headers={"Content-Type": "image/png"},
        )
        self.assertEqual(201, uploaded.status_code)
        plan = self.client.post(f"/api/projects/{project_id}/plan").json()
        confirmed = self.client.put(
            f"/api/projects/{project_id}/plan",
            json={"items": plan["items"], "confirmed": True},
        )
        self.assertEqual(200, confirmed.status_code)
        return project_id

    def test_full_production_review_and_export(self) -> None:
        project_id = self._create_planned_project()

        started = self.client.post(
            f"/api/projects/{project_id}/production/start",
            json={"recipe_id": "commerce-detail-v1", "force": False},
        )

        self.assertEqual(202, started.status_code)
        snapshot = self.client.get(f"/api/projects/{project_id}/production").json()
        self.assertEqual(5, len(snapshot["pages"]))
        self.assertTrue(all(row["job"]["status"] == "completed" for row in snapshot["pages"]))
        self.assertTrue(all(len(row["candidates"]) == 2 for row in snapshot["pages"]))
        self.assertTrue(all(row["job"]["trace"]["reference_count"] == 1 for row in snapshot["pages"]))
        self.assertTrue(all(row["job"]["trace"]["progress"] == 100 for row in snapshot["pages"]))
        self.assertTrue(all(
            {"generating_background", "compositing_product", "compositing_text", "finalizing"}
            <= {event["stage"] for event in row["job"]["trace"]["stage_history"]}
            for row in snapshot["pages"]
        ))
        self.assertTrue(all(
            row["candidates"][0]["metadata"]["generator"]["source_reference"]
            for row in snapshot["pages"]
        ))
        self.assertTrue(all(
            row["candidates"][0]["qa"]["evidence"]["reference_consistency"]["reference_count"] == 1
            for row in snapshot["pages"]
        ))
        first_candidate = snapshot["pages"][0]["candidates"][0]
        self.assertEqual(200, self.client.get(first_candidate["base_url"]).status_code)
        self.assertEqual(200, self.client.get(first_candidate["text_layer_url"]).status_code)
        self.assertEqual(200, self.client.get(first_candidate["composed_url"]).status_code)

        for row in snapshot["pages"]:
            candidate = row["candidates"][0]
            reviewed = self.client.post(
                f"/api/candidates/{candidate['id']}/review",
                json={"decision": "approved", "reviewer": "qa-test", "override_reason": ""},
            )
            self.assertEqual(200, reviewed.status_code, reviewed.text)

        completed = self.client.get(f"/api/projects/{project_id}").json()
        self.assertEqual("completed", completed["status"])
        exported = self.client.post(f"/api/projects/{project_id}/export")
        self.assertEqual(201, exported.status_code, exported.text)
        archive = self.client.get(exported.json()["download_url"])
        self.assertEqual(200, archive.status_code)
        with zipfile.ZipFile(io.BytesIO(archive.content)) as delivery:
            names = set(delivery.namelist())
            self.assertIn("project_summary.json", names)
            self.assertIn("pages/01_hero/final.png", names)
            self.assertIn("pages/01_hero/base.png", names)
            self.assertIn("pages/01_hero/text_layer.png", names)
            self.assertIn("pages/01_hero/qa.json", names)
            summary = json.loads(delivery.read("project_summary.json"))
            first_page = summary["pages"][0]
            self.assertEqual("commerce-detail-v1", first_page["recipe_id"])
            self.assertEqual("local-preview", first_page["generator_provider"])
            self.assertEqual("2048x2048", first_page["effective_generation"]["size"])
            self.assertEqual(
                ["base.png", "text_layer.png", "final.png"],
                first_page["layer_files"],
            )

    def test_lifestyle_demo_recipe_runs_custom_template_with_quality_override(self) -> None:
        project_id = self._create_planned_project()
        detail = io.BytesIO()
        Image.new("RGB", (320, 320), "#31383a").save(detail, format="PNG")
        uploaded_detail = self.client.post(
            f"/api/projects/{project_id}/assets?file_name=x11-detail.png&usage=detail",
            content=detail.getvalue(),
            headers={"Content-Type": "image/png"},
        )
        self.assertEqual(201, uploaded_detail.status_code)
        uploaded_brand = self.client.post(
            f"/api/projects/{project_id}/assets?file_name=brand-board.png&usage=brand",
            content=detail.getvalue(),
            headers={"Content-Type": "image/png"},
        )
        self.assertEqual(201, uploaded_brand.status_code)
        template_response = self.client.post(
            "/api/templates",
            json={
                "name": "演示方图生活场景",
                "page_types": ["scene"],
                "base_template_id": "scene-overlay",
                "size": "1024x1024",
            },
        )
        self.assertEqual(201, template_response.status_code, template_response.text)
        template = template_response.json()

        plan = self.client.get(f"/api/projects/{project_id}/plan").json()
        scene = next(item for item in plan["items"] if item["page_type"] == "scene")
        scene.update({
            "order": 1,
            "title": "让精致护理融入生活",
            "body": "自然光与温润材质，共同构成安静而真实的洗护空间。",
            "visual_goal": "高端住宅洗衣房，石材地面、木饰面、绿植与晨间自然光，商品右下完整呈现",
            "template_id": template["id"],
        })
        confirmed = self.client.put(
            f"/api/projects/{project_id}/plan",
            json={"items": [scene], "confirmed": True},
        )
        self.assertEqual(200, confirmed.status_code, confirmed.text)

        demo_prompt = next(
            item for item in self.client.get("/api/prompts").json()
            if item["id"] == "prompt-lifestyle-scene-v3"
        )
        recipe_response = self.client.post(
            "/api/recipes",
            json={
                "name": "最小生活场景演示配方",
                "prompt_version_id": demo_prompt["id"],
                "model": "local-preview",
                "model_params": {"quality": "high", "reference_strategy": "model_edit"},
                "template_ids": [template["id"]],
                "qa_policy": "commerce-basic-v1",
                "candidate_count": 1,
            },
        )
        self.assertEqual(201, recipe_response.status_code, recipe_response.text)
        published_recipe = self.client.post(
            f"/api/recipes/{recipe_response.json()['id']}/publish"
        )
        self.assertEqual(200, published_recipe.status_code, published_recipe.text)

        started = self.client.post(
            f"/api/projects/{project_id}/production/start",
            json={
                "recipe_id": published_recipe.json()["id"],
                "force": False,
                "quality": "medium",
            },
        )
        self.assertEqual(202, started.status_code, started.text)
        snapshot = self.client.get(f"/api/projects/{project_id}/production").json()
        self.assertEqual(1, len(snapshot["pages"]))
        row = snapshot["pages"][0]
        self.assertEqual("completed", row["job"]["status"])
        self.assertEqual("medium", row["job"]["trace"]["quality"])
        self.assertTrue(row["job"]["trace"]["quality_overridden"])
        candidate = row["candidates"][0]
        self.assertEqual(
            {
                "size": "1024x1024",
                "quality": "medium",
                "template_id": template["id"],
                "reference_strategy": "model_edit",
                "max_auto_regenerations": 0,
            },
            candidate["metadata"]["effective_generation"],
        )
        self.assertIn("完整环境叙事", candidate["prompt"])
        self.assertIn("全部商品外观图和局部细节图", candidate["prompt"])
        self.assertIn("不能复制粘贴、抠图贴层", candidate["prompt"])
        self.assertEqual(2, row["job"]["trace"]["reference_count"])
        self.assertIn("高端住宅洗衣房", candidate["prompt"])
        self.assertNotIn(scene["title"], candidate["prompt"])
        self.assertNotIn(scene["body"], candidate["prompt"])

        base_response = self.client.get(candidate["base_url"])
        composed_response = self.client.get(candidate["composed_url"])
        with Image.open(io.BytesIO(base_response.content)) as base_image:
            self.assertEqual((1024, 1024), base_image.size)
        with Image.open(io.BytesIO(composed_response.content)) as composed_image:
            self.assertEqual((1024, 1024), composed_image.size)

    def test_app_restart_marks_interrupted_jobs_failed(self) -> None:
        project_id = self._create_planned_project()
        production = self.client.app.state.production
        jobs = production.start_project(project_id)
        timestamp = datetime.now(timezone.utc)
        production._repository.update_job(
            replace(
                jobs[-1],
                status=JobStatus.RUNNING,
                attempt=1,
                trace={**jobs[-1].trace, "stage": "generating"},
                updated_at=timestamp,
            )
        )

        production.recover_interrupted()

        snapshot = production.get_project_production(project_id)
        self.assertTrue(all(row["job"].status is JobStatus.FAILED for row in snapshot["pages"]))
        recovered = snapshot["pages"][-1]["job"]
        self.assertEqual(JobStatus.FAILED, recovered.status)
        self.assertEqual("interrupted", recovered.trace["stage"])
        self.assertIn("重试生产", recovered.error)
        self.assertEqual("reviewing", snapshot["project"].status.value)

    def test_prompt_and_recipe_publish_workflow(self) -> None:
        prompt = self.client.post(
            "/api/prompts",
            json={
                "name": "新品 Prompt",
                "body": "为{{product_name}}制作{{page_title}}页面",
                "variables": ["product_name", "page_title"],
                "change_note": "测试版本",
            },
        )
        self.assertEqual(201, prompt.status_code)
        prompt_id = prompt.json()["id"]
        self.assertEqual("draft", prompt.json()["status"])
        self.assertEqual(200, self.client.post(f"/api/prompts/{prompt_id}/publish").status_code)

        recipe = self.client.post(
            "/api/recipes",
            json={
                "name": "新品配方",
                "prompt_version_id": prompt_id,
                "model": "local-preview",
                "model_params": {"size": "900x1200"},
                "template_ids": ["hero-center", "split-left"],
                "candidate_count": 1,
            },
        )
        self.assertEqual(201, recipe.status_code, recipe.text)
        recipe_id = recipe.json()["id"]
        published = self.client.post(f"/api/recipes/{recipe_id}/publish")
        self.assertEqual(200, published.status_code, published.text)
        self.assertEqual("published", published.json()["status"])

    def test_multi_sku_batch_production_review_and_export(self) -> None:
        def profile(sku: str) -> dict[str, object]:
            return {
                "sku": sku, "name": f"COLMO {sku}", "category": "洗衣机", "model": sku,
                "selling_points": ["智能护理", "低温柔洗"], "parameters": {"容量": "12kg"},
                "reference_assets": [], "brand_requirements": "", "output_requirements": "",
            }

        batch = self.client.post(
            "/api/batches",
            json={
                "name": "多SKU完整生产",
                "common_config": {"recipe_id": "commerce-detail-v1"},
                "skus": [{"profile": profile("X11")}, {"profile": profile("T1")}],
            },
        ).json()
        batch_id = batch["id"]

        started = self.client.post(
            f"/api/batches/{batch_id}/production/start",
            json={"recipe_id": "commerce-detail-v1", "force": False},
        )

        self.assertEqual(202, started.status_code, started.text)
        after_generation = self.client.get(f"/api/batches/{batch_id}").json()
        self.assertEqual(2, after_generation["progress"]["needs_review"])
        for item in after_generation["items"]:
            snapshot = self.client.get(f"/api/projects/{item['project_id']}/production").json()
            for row in snapshot["pages"]:
                approved = self.client.post(
                    f"/api/candidates/{row['candidates'][0]['id']}/review",
                    json={"decision": "approved", "override_reason": "", "reviewer": "batch-test"},
                )
                self.assertEqual(200, approved.status_code, approved.text)

        completed = self.client.get(f"/api/batches/{batch_id}").json()
        self.assertEqual(2, completed["progress"]["completed"])
        exported = self.client.post(f"/api/batches/{batch_id}/export")
        self.assertEqual(201, exported.status_code, exported.text)
        archive = self.client.get(exported.json()["download_url"])
        with zipfile.ZipFile(io.BytesIO(archive.content)) as delivery:
            names = set(delivery.namelist())
            self.assertIn("batch_summary.json", names)
            self.assertIn("X11/pages/01_hero/final.png", names)
            self.assertIn("T1/pages/05_parameters/qa.json", names)

    def test_recompose_reuses_base_and_requires_new_review(self) -> None:
        project_id = self._create_planned_project()
        self.client.post(
            f"/api/projects/{project_id}/production/start",
            json={"recipe_id": "commerce-detail-v1", "force": False},
        )
        before = self.client.get(f"/api/projects/{project_id}/production").json()
        first_page = before["pages"][0]
        source_candidate = first_page["candidates"][0]
        self.client.post(
            f"/api/candidates/{source_candidate['id']}/review",
            json={"decision": "approved", "override_reason": "", "reviewer": "layout-test"},
        )
        plan = self.client.get(f"/api/projects/{project_id}/plan").json()
        plan["items"][0]["title"] = "修改后的分层标题"
        self.client.put(
            f"/api/projects/{project_id}/plan",
            json={"items": plan["items"], "confirmed": True},
        )

        recomposed = self.client.post(
            f"/api/projects/{project_id}/pages/{first_page['page']['id']}/recompose"
        )

        self.assertEqual(200, recomposed.status_code, recomposed.text)
        first_after = recomposed.json()["pages"][0]
        self.assertEqual("rejected", first_after["decision"]["decision"])
        new_candidate = first_after["candidates"][0]
        old_base = self.client.get(source_candidate["base_url"]).content
        new_base = self.client.get(new_candidate["base_url"]).content
        self.assertEqual(old_base, new_base)
        self.assertNotEqual(
            self.client.get(source_candidate["text_layer_url"]).content,
            self.client.get(new_candidate["text_layer_url"]).content,
        )

    def test_project_edit_clone_page_regenerate_and_recipe_candidate(self) -> None:
        project_id = self._create_planned_project()
        project = self.client.get(f"/api/projects/{project_id}").json()
        project["profile"]["selling_points"].append("新增卖点")
        updated = self.client.put(
            f"/api/projects/{project_id}",
            json={"project_name": "X11 更新版", "profile": project["profile"]},
        )
        self.assertEqual(200, updated.status_code, updated.text)
        self.assertEqual("X11 更新版", updated.json()["name"])

        clone = self.client.post(f"/api/projects/{project_id}/clone")
        self.assertEqual(201, clone.status_code, clone.text)
        self.assertEqual(5, len(self.client.get(f"/api/projects/{clone.json()['id']}/plan").json()["items"]))

        self.client.post(
            f"/api/projects/{project_id}/production/start",
            json={"recipe_id": "commerce-detail-v1", "force": False},
        )
        snapshot = self.client.get(f"/api/projects/{project_id}/production").json()
        for row in snapshot["pages"]:
            self.client.post(
                f"/api/candidates/{row['candidates'][0]['id']}/review",
                json={"decision": "approved", "override_reason": "", "reviewer": "flow-test"},
            )
        recipe = self.client.post(
            f"/api/projects/{project_id}/recipe-candidate", json={"name": "X11 验证配方"}
        )
        self.assertEqual(201, recipe.status_code, recipe.text)
        self.assertEqual("draft", recipe.json()["status"])
        published_recipe = self.client.post(f"/api/recipes/{recipe.json()['id']}/publish")
        self.assertEqual(200, published_recipe.status_code, published_recipe.text)
        clone_plan = self.client.get(f"/api/projects/{clone.json()['id']}/plan").json()
        confirmed_clone = self.client.put(
            f"/api/projects/{clone.json()['id']}/plan",
            json={"items": clone_plan["items"], "confirmed": True},
        )
        self.assertEqual(200, confirmed_clone.status_code, confirmed_clone.text)
        clone_started = self.client.post(
            f"/api/projects/{clone.json()['id']}/production/start",
            json={"recipe_id": published_recipe.json()["id"], "force": False},
        )
        self.assertEqual(202, clone_started.status_code, clone_started.text)
        clone_snapshot = self.client.get(
            f"/api/projects/{clone.json()['id']}/production"
        ).json()
        self.assertTrue(all(
            row["job"]["status"] == "completed"
            and row["job"]["recipe_id"] == published_recipe.json()["id"]
            for row in clone_snapshot["pages"]
        ))

        page_id = snapshot["pages"][0]["page"]["id"]
        regenerated = self.client.post(
            f"/api/projects/{project_id}/pages/{page_id}/regenerate",
            json={"recipe_id": "commerce-detail-v1", "force": True},
        )
        self.assertEqual(202, regenerated.status_code, regenerated.text)
        after = self.client.get(f"/api/projects/{project_id}/production").json()
        self.assertFalse(after["ready_for_export"])
        self.assertEqual("rejected", after["pages"][0]["decision"]["decision"])


if __name__ == "__main__":
    unittest.main()
