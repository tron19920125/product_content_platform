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
