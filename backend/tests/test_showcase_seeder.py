from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from product_content_platform.adapters import (
    LocalAssetStore,
    SQLitePlatformRepository,
    SQLiteProductionRepository,
    seed_showcase_projects,
)
from product_content_platform.adapters.showcase_seeder import AZURE_ACCEPTANCE_PROJECT_ID
from product_content_platform.api import create_app


class ShowcaseSeederTest(unittest.TestCase):
    def test_clean_deployment_restores_approved_azure_five_page_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "platform.db"
            production_root = root / "production"
            asset_root = root / "assets"
            app = create_app(
                database_path=database,
                asset_root=asset_root,
                production_root=production_root,
                export_root=root / "exports",
            )
            repository = SQLitePlatformRepository(database)
            production_repository = SQLiteProductionRepository(database)
            asset_store = LocalAssetStore(asset_root)
            source_root = Path(__file__).resolve().parents[2] / "examples" / "showcases"

            def seed() -> None:
                seed_showcase_projects(
                    source_root=source_root,
                    production_root=production_root,
                    repository=repository,
                    platform=app.state.platform,
                    production_repository=production_repository,
                    asset_store=asset_store,
                )

            seed()
            seed()  # The deployment hook must be safe on every service restart.

            with TestClient(app) as client:
                project = client.get(f"/api/projects/{AZURE_ACCEPTANCE_PROJECT_ID}")
                self.assertEqual(200, project.status_code, project.text)
                self.assertEqual("Azure 2048 High Five Page Acceptance", project.json()["name"])
                self.assertEqual("completed", project.json()["status"])

                plan = client.get(f"/api/projects/{AZURE_ACCEPTANCE_PROJECT_ID}/plan").json()
                self.assertTrue(plan["confirmed"])
                self.assertEqual("library-square-2048", plan["layout_library_id"])
                self.assertEqual(5, len(plan["items"]))

                snapshot = client.get(
                    f"/api/projects/{AZURE_ACCEPTANCE_PROJECT_ID}/production"
                ).json()
                self.assertTrue(snapshot["ready_for_export"])
                self.assertEqual(5, len(snapshot["pages"]))
                for page in snapshot["pages"]:
                    self.assertEqual("completed", page["job"]["status"])
                    self.assertEqual("approved", page["decision"]["decision"])
                    self.assertEqual(1, len(page["candidates"]))
                    candidate = page["candidates"][0]
                    self.assertEqual(98, candidate["score"])
                    self.assertEqual("pass", candidate["qa"]["status"])
                    self.assertEqual(
                        "azure-gpt-image", candidate["metadata"]["generator"]["provider"]
                    )
                    image = client.get(candidate["composed_url"])
                    self.assertEqual(200, image.status_code)
                    self.assertGreater(len(image.content), 1_000_000)

                portrait = client.get("/api/candidates/showcase-portrait-3840-candidate-1/text-document")
                self.assertEqual(200, portrait.status_code, portrait.text)
                portrait_document = portrait.json()
                self.assertEqual("candidate", portrait_document["source"])
                self.assertEqual("system_sans", portrait_document["layers"][0]["font_family"])
                self.assertEqual(400, portrait_document["layers"][0]["font_weight"])
                self.assertEqual("#1F3027", portrait_document["layers"][0]["color"])

                jobs = client.get(
                    "/api/jobs", params={"project_id": AZURE_ACCEPTANCE_PROJECT_ID}
                ).json()
                self.assertEqual(5, len(jobs))

                exported = client.post(
                    f"/api/projects/{AZURE_ACCEPTANCE_PROJECT_ID}/export"
                )
                self.assertEqual(201, exported.status_code, exported.text)
                archive_path = root / "exports" / exported.json()["file_name"]
                self.assertTrue(archive_path.is_file())
                self.assertGreater(archive_path.stat().st_size, 20_000_000)


if __name__ == "__main__":
    unittest.main()
