from __future__ import annotations

import io
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from PIL import Image

from product_content_platform.adapters import SQLitePlatformRepository
from product_content_platform.api import create_app
from product_content_platform.application import PlatformApplication, PlanningApplication, ProjectInput
from product_content_platform.domain import ProductProfile
from product_content_platform.planning import ContentPlanner


TEMPLATES = [
    {
        "id": "hero", "name": "主视觉", "page_types": ["hero"],
        "scene_prompt_hint": "自然光空间", "composition_instruction": "上方留白",
    },
    {
        "id": "feature", "name": "卖点", "page_types": ["selling_point", "function", "scene", "parameters"],
        "scene_prompt_hint": "材质展台", "composition_instruction": "左文右图",
    },
]


def test_planner_rejects_invented_numbers_and_falls_back() -> None:
    planner = ContentPlanner("azure")
    profile = ProductProfile(
        sku="SKU-12", name="测试洗衣机", category="洗衣机", model="X12",
        selling_points=("低温柔洗",), parameters={"容量": "12kg"},
    )
    specs = [{
        "key": "page-1", "page_type": "hero", "template_id": "hero",
        "template_name": "主视觉", "scene_prompt_hint": "自然光", "composition_instruction": "上方留白",
    }]
    fallback = planner._fallback(profile, specs, planner._facts(profile))
    parsed = planner._parse(
        {"pages": [{
            "key": "page-1", "title": "36项认证", "body": "容量 36kg",
            "visual_goal": "自然光空间", "fact_refs": [], "reasoning": "展示参数",
        }]}, profile, specs, planner._facts(profile), fallback,
    )
    assert parsed["pages"][0]["title"] == "测试洗衣机"
    assert "未确认数字 36" in parsed["warnings"][0]


def test_planning_run_applies_selected_fields_and_keeps_audit() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        repository = SQLitePlatformRepository(root / "platform.db")
        platform = PlatformApplication(repository)
        project = platform.create_project(ProjectInput(
            project_name="规划测试",
            profile=ProductProfile(
                sku="PLAN-1", name="测试商品", category="洗衣机",
                selling_points=("静音洗护", "智能投放"), parameters={"容量": "10kg"},
            ),
        ))
        application = PlanningApplication(platform, repository, ContentPlanner("local"), lambda path: root / path)
        run = application.start(project.id, "library-square-2048", TEMPLATES)
        completed = application.process(run.id)
        first = completed.suggestion["pages"][0]
        plan = application.apply(project.id, run.id)
        assert plan.items[0].title == first["title"]

        original_body = plan.items[0].body
        second = application.start(project.id, "library-square-2048", TEMPLATES)
        second = application.process(second.id)
        updated = application.apply(project.id, second.id, {plan.items[0].id: ["title"]})
        assert updated.items[0].body == original_body
        audit = application.get(second.id)
        assert audit.applied_fields[plan.items[0].id] == ["title"]
        assert audit.applied_plan_version == updated.version


def test_planning_api_redacts_storage_paths_and_persists_dismissal() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        with TestClient(create_app(
            database_path=root / "platform.db",
            asset_root=root / "assets",
            production_root=root / "production",
            export_root=root / "exports",
        )) as client:
            project = client.post("/api/projects", json={
                "project_name": "planning-api",
                "profile": {
                    "sku": "PLAN-API", "name": "Test product", "category": "Appliance",
                    "selling_points": ["Quiet care"], "parameters": {"capacity": "10kg"},
                },
            }).json()
            image = io.BytesIO()
            Image.new("RGB", (16, 16), "white").save(image, format="PNG")
            uploaded = client.post(
                f"/api/projects/{project['id']}/assets?file_name=reference.png&usage=product",
                content=image.getvalue(),
                headers={"Content-Type": "image/png"},
            )
            assert uploaded.status_code == 201

            started = client.post(
                f"/api/projects/{project['id']}/planning-runs",
                json={"layout_library_id": "library-square-2048"},
            )
            assert started.status_code == 202
            run = client.get(
                f"/api/projects/{project['id']}/planning-runs/{started.json()['id']}"
            ).json()
            assert run["status"] == "completed"
            assert "storage_path" not in run["input_snapshot"]["assets"][0]

            dismissed = client.post(
                f"/api/projects/{project['id']}/planning-runs/{run['id']}/dismiss"
            )
            assert dismissed.status_code == 200
            assert dismissed.json()["status"] == "dismissed"
