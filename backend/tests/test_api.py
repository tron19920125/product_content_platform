from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from product_content_platform.api import create_app


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.client = TestClient(
            create_app(database_path=root / "platform.db", asset_root=root / "assets")
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    @staticmethod
    def profile_payload(sku: str) -> dict[str, object]:
        return {
            "sku": sku,
            "name": f"测试商品 {sku}",
            "category": "洗衣机",
            "model": sku,
            "selling_points": ["低温柔洗"],
            "parameters": {"容量": "12kg"},
            "reference_assets": [],
            "brand_requirements": "",
            "output_requirements": "",
        }

    def test_health_and_project_round_trip(self) -> None:
        self.assertEqual({"status": "ok"}, self.client.get("/api/health").json())

        response = self.client.post(
            "/api/projects",
            json={"project_name": "X11详情页", "profile": self.profile_payload("X11")},
        )

        self.assertEqual(201, response.status_code)
        project_id = response.json()["id"]
        listed = self.client.get("/api/projects").json()
        self.assertEqual(project_id, listed[0]["id"])

    def test_font_catalog_exposes_preview_and_license_metadata(self) -> None:
        response = self.client.get("/api/fonts")
        self.assertEqual(200, response.status_code)
        fonts = response.json()
        self.assertGreaterEqual(len(fonts), 8)
        self.assertTrue({"现代黑体", "宋体衬线", "艺术标题", "书法"} <= {item["category"] for item in fonts})
        self.assertTrue(all(item["preview"] and item["license"] == "OFL-1.1" for item in fonts))
        self.assertTrue(all(item["commercial_use"] for item in fonts))
        available = [item for item in fonts if item["preview_available"]]
        self.assertGreaterEqual(len(available), 7)
        preview = self.client.get(available[0]["content_url"])
        self.assertEqual(200, preview.status_code)
        self.assertGreater(len(preview.content), 16_000)

    def test_create_laundry_golden_demo_is_ready_for_reference_upload(self) -> None:
        response = self.client.post("/api/demo-projects/laundry")

        self.assertEqual(201, response.status_code, response.text)
        payload = response.json()
        self.assertEqual("commerce-lifestyle-demo-v1", payload["recipe_id"])
        self.assertEqual("high", payload["quality"])
        self.assertEqual("planned", payload["project"]["status"])
        self.assertTrue(payload["plan"]["confirmed"])
        self.assertEqual(1, len(payload["plan"]["items"]))
        page = payload["plan"]["items"][0]
        self.assertEqual("scene-overlay", page["template_id"])
        self.assertEqual("静谧洗护，自成风景", page["title"])
        self.assertEqual(2, page["heading_level"])

    def test_image_capabilities_and_custom_template_validation(self) -> None:
        capabilities = self.client.get("/api/image-capabilities")
        self.assertEqual(200, capabilities.status_code)
        payload = capabilities.json()
        self.assertEqual("gpt-image-2", payload["model"])
        self.assertEqual(["low", "medium", "high"], payload["qualities"])
        self.assertEqual("2880x2880", payload["custom_size"]["max_square"])

        created = self.client.post(
            "/api/templates",
            json={
                "name": "最大正方形生活场景",
                "page_types": ["scene"],
                "base_template_id": "scene-overlay",
                "size": "2880x2880",
            },
        )
        self.assertEqual(201, created.status_code, created.text)
        self.assertEqual("2880x2880", created.json()["size"])
        self.assertFalse(created.json()["is_builtin"])

        oversized = self.client.post(
            "/api/templates",
            json={
                "name": "超过总像素限制",
                "page_types": ["scene"],
                "base_template_id": "scene-overlay",
                "size": "2896x2896",
            },
        )
        self.assertEqual(422, oversized.status_code)
        self.assertIn("总像素", oversized.json()["detail"])

    def test_create_multi_sku_batch(self) -> None:
        response = self.client.post(
            "/api/batches",
            json={
                "name": "洗护批次",
                "common_config": {"recipe_id": "hero"},
                "skus": [
                    {"profile": self.profile_payload("X11"), "override_config": {}},
                    {"profile": self.profile_payload("T1"), "override_config": {}},
                ],
            },
        )

        self.assertEqual(201, response.status_code)
        payload = response.json()
        self.assertEqual("ready", payload["status"])
        self.assertEqual(2, payload["progress"]["total"])
        self.assertEqual({"X11", "T1"}, {item["sku"] for item in payload["items"]})

    def test_duplicate_sku_returns_domain_error(self) -> None:
        response = self.client.post(
            "/api/batches",
            json={
                "name": "重复批次",
                "skus": [
                    {"profile": self.profile_payload("X11")},
                    {"profile": self.profile_payload("X11")},
                ],
            },
        )

        self.assertEqual(422, response.status_code)
        self.assertIn("重复SKU", response.json()["detail"])

    def test_upload_asset_and_generate_confirmed_plan(self) -> None:
        project = self.client.post(
            "/api/projects",
            json={"project_name": "X11详情页", "profile": self.profile_payload("X11")},
        ).json()
        buffer = BytesIO()
        Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
        uploaded = self.client.post(
            f"/api/projects/{project['id']}/assets?file_name=front.png&usage=product",
            content=buffer.getvalue(),
            headers={"Content-Type": "image/png"},
        )
        self.assertEqual(201, uploaded.status_code)
        asset = uploaded.json()
        self.assertEqual("front.png", asset["file_name"])
        self.assertNotIn("authorization_status", asset)
        self.assertEqual(buffer.getvalue(), self.client.get(asset["content_url"]).content)

        generated = self.client.post(f"/api/projects/{project['id']}/plan")
        self.assertEqual(201, generated.status_code)
        plan = generated.json()
        self.assertEqual(5, len(plan["items"]))
        self.assertEqual([1, 2, 2, 2, 2], [item["heading_level"] for item in plan["items"]])
        plan["items"][0]["title"] = "确认后的主视觉"
        confirmed = self.client.put(
            f"/api/projects/{project['id']}/plan",
            json={"items": plan["items"], "confirmed": True},
        )
        self.assertEqual(200, confirmed.status_code)
        self.assertTrue(confirmed.json()["confirmed"])

    def test_plan_uses_one_layout_library_and_rejects_cross_library_templates(self) -> None:
        project = self.client.post(
            "/api/projects",
            json={"project_name": "横版详情页", "profile": self.profile_payload("WIDE-01")},
        ).json()
        generated = self.client.post(
            f"/api/projects/{project['id']}/plan",
            json={"layout_library_id": "library-landscape-3840"},
        )
        self.assertEqual(201, generated.status_code, generated.text)
        plan = generated.json()
        self.assertEqual("library-landscape-3840", plan["layout_library_id"])
        landscape_ids = {item["id"] for item in self.client.get(
            "/api/templates?library_id=library-landscape-3840"
        ).json()}
        self.assertTrue({item["template_id"] for item in plan["items"]} <= landscape_ids)

        plan["items"][0]["template_id"] = "hero-center"
        rejected = self.client.put(
            f"/api/projects/{project['id']}/plan",
            json={
                "layout_library_id": "library-landscape-3840",
                "items": plan["items"],
                "confirmed": True,
            },
        )
        self.assertEqual(422, rejected.status_code)
        self.assertIn("不属于当前版式库", rejected.json()["detail"])

    def test_import_batch_from_csv(self) -> None:
        content = (
            "SKU,商品名称,品类,型号,卖点,参数\n"
            "X11,COLMO X11,洗衣机,CGU12W-X11,低温柔洗|智能投放,容量=12kg|洗净比=1.1\n"
            "T1,COLMO T1,干衣机,T1,热泵柔烘,容量=10kg\n"
            "T2,COLMO T2,干衣机,T2,智能烘干,容量=10kg\n"
            "W1,COLMO W1,洗衣机,W1,精细洗护,容量=12kg\n"
            "S1,COLMO S1,洗烘套装,S1,智能联动,容量=12kg\n"
        ).encode("utf-8")
        response = self.client.post(
            "/api/batches-import?name=洗护导入批次&file_name=skus.csv",
            content=content,
            headers={"Content-Type": "text/csv"},
        )

        self.assertEqual(201, response.status_code)
        self.assertEqual(5, response.json()["progress"]["total"])


if __name__ == "__main__":
    unittest.main()
