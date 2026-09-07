from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from product_content_platform.studio.api import create_app
from product_content_platform.studio.catalog import DraftContent
from product_content_platform.studio.planning import PlanResult, PlannedPage, apply_plan
from product_content_platform.studio.settings import StudioSettings


class FakePlanner:
    def __init__(self):
        self.calls = 0

    def plan(self, content: DraftContent) -> PlanResult:
        self.calls += 1
        return PlanResult(pages=[
            PlannedPage(purpose="hero", title="Quietly designed", body="A place in your home.", visual_goal="Warm laundry room"),
            PlannedPage(purpose="detail", title="Thoughtful details", body="", visual_goal="Close view of visible materials"),
        ])


class PlanningTest(unittest.TestCase):
    def test_plan_replaces_modules_but_keeps_inputs_and_gets_new_page_ids(self):
        original = DraftContent.model_validate({
            "tool": "a_plus_detail", "product_name": "Washer",
            "product_asset_ids": [], "pages": [{"id": "old", "purpose": "hero"}],
        })
        changed = apply_plan(original, FakePlanner().plan(original))
        self.assertEqual("Washer", changed.product_name)
        self.assertEqual(["hero", "detail"], [page.purpose for page in changed.pages])
        self.assertNotIn("old", [page.id for page in changed.pages])

    def test_api_uses_injected_planner_and_keeps_revision_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            planner = FakePlanner()
            with TestClient(create_app(StudioSettings(Path(directory)), planner=planner)) as client:
                draft = client.post("/api/studio/drafts", json={"tool": "a_plus_detail"}).json()
                response = client.post(f"/api/studio/drafts/{draft['id']}/plan", json={"expected_revision": 1})
                self.assertEqual(200, response.status_code)
                self.assertEqual(2, response.json()["revision"])
                self.assertEqual(1, planner.calls)
                plans = client.get(f"/api/studio/drafts/{draft['id']}/plans").json()
                self.assertEqual(["智能模块方案", "重新规划前"], [row["label"] for row in plans])
                before = next(row for row in plans if row["label"] == "重新规划前")
                restored = client.post(
                    f"/api/studio/drafts/{draft['id']}/plans/{before['id']}/restore",
                    json={"expected_revision": 2},
                )
                self.assertEqual(200, restored.status_code, restored.text)
                self.assertEqual(3, restored.json()["revision"])
                self.assertEqual(3, len(restored.json()["content"]["pages"]))
                stale = client.post(f"/api/studio/drafts/{draft['id']}/plan", json={"expected_revision": 1})
                self.assertEqual(409, stale.status_code)


if __name__ == "__main__":
    unittest.main()
