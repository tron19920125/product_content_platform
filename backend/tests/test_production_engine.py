from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from product_content_platform.adapters.production_engine import LocalProductionEngine
from product_content_platform.domain import (
    PageItem,
    PageStatus,
    PageType,
    ProductProfile,
    Project,
    PromptVersion,
    PublishStatus,
    Recipe,
)


class RepairingGenerator:
    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []

    def generate(self, *, prompt, profile, reference_paths, output_path, variant, size, quality):
        self.calls += 1
        self.prompts.append(prompt)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = (int(value) for value in size.split("x", 1))
        image = Image.new("RGB", (width, height), "#20352b")
        draw = ImageDraw.Draw(image)
        product_bbox = (500, 350, 850, 1050)
        draw.rectangle(product_bbox, fill="black" if self.calls == 1 else "white")
        image.save(output_path)
        return {
            "provider": "repair-test",
            "source_reference": str(reference_paths[0]),
            "product_bbox": list(product_bbox),
        }


class QualityStub:
    def repair_prompt(self, original_prompt, suggested_fix, title, body):
        return f"{original_prompt}\n自动修复：{suggested_fix}"

    def review_plan(self, prompt):
        return {"mode": "generate", "prompt": prompt}

    def review_known_text(self, **kwargs):
        return {"status": "pass", "issues": []}

    def visual_evidence(self, reference_path, output_path, target_region):
        return {"status": "pass", "target_region": target_region}

    def rank(self, rows):
        return {
            row["candidate_index"]: {
                "rank": index,
                "score": {
                    "overall": row["score"],
                    "breakdown": {
                        "text_accuracy": 100,
                        "product_consistency": 100,
                        "layout_stability": 100,
                        "brand_compliance": 100,
                    },
                },
            }
            for index, row in enumerate(rows, start=1)
        }


class ProductionEngineTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows Chinese font discovery")
    def test_windows_composition_font_supports_distinct_chinese_glyphs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = LocalProductionEngine(Path(directory), RepairingGenerator(), QualityStub())

            self.assertIsNotNone(engine._font_path)
            self.assertIn(engine._font_path.name.lower(), {"msyh.ttc", "msyhbd.ttc", "deng.ttf", "simhei.ttf", "simsun.ttc"})
            font = engine._font(48)
            self.assertNotEqual(bytes(font.getmask("测")), bytes(font.getmask("试")))

    def test_reference_failure_triggers_exactly_one_repair_and_keeps_before_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.png"
            Image.new("RGB", (350, 700), "white").save(reference)
            generator = RepairingGenerator()
            engine = LocalProductionEngine(root / "production", generator, QualityStub())
            profile = ProductProfile(
                sku="X11", name="X11洗衣机", category="洗衣机", model="X11",
                selling_points=("智能护理",), parameters={"容量": "12kg"},
            )
            page = PageItem(
                id="page-1", order=1, page_type=PageType.SELLING_POINT,
                title="智能护理", body="柔和呵护衣物", visual_goal="商品主体清晰",
                template_id="split-left", status=PageStatus.READY,
            )
            prompt = PromptVersion(
                id="prompt-1", prompt_asset_id="asset-1", name="测试 Prompt", version=1,
                body="为{{product_name}}制作{{page_title}}", variables=("product_name", "page_title"),
                status=PublishStatus.PUBLISHED,
            )
            recipe = Recipe(
                id="recipe-1", name="测试配方", status=PublishStatus.PUBLISHED,
                prompt_version_id=prompt.id, model="repair-test", model_params={},
                template_ids=("split-left",), qa_policy="test", candidate_count=1,
            )

            result = engine.execute(
                project=Project(id="project-1", name="测试项目", profile=profile),
                page=page,
                recipe=recipe,
                prompt_version=prompt,
                reference_paths=[reference],
            )[0]

            self.assertEqual(2, generator.calls)
            self.assertTrue(result.repair_applied)
            history = result.metadata["repair_history"]
            self.assertEqual(1, len(history))
            self.assertTrue(engine.resolve(history[0]["before"]["base_path"]).exists())
            self.assertGreaterEqual(result.evidence["reference_consistency"]["product_similarity"], .99)
            self.assertNotIn(page.title, generator.prompts[0])
            self.assertNotIn(page.body, generator.prompts[0])
            self.assertIn("左侧 7%-43%", generator.prompts[0])
            self.assertIn("预留文字区域内严禁出现标题", generator.prompts[0])
            self.assertIn(page.title, result.metadata["content_review_prompt"])

    def test_2048_composition_scales_copy_and_uses_dark_text_on_light_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.png"
            text = root / "text.png"
            composed = root / "composed.png"
            Image.new("RGB", (2048, 2048), "white").save(base)
            engine = LocalProductionEngine(root / "production", RepairingGenerator(), QualityStub())
            page = PageItem(
                id="page-layout", order=1, page_type=PageType.SELLING_POINT,
                title="智能科技", body="专业呵护每一次使用", visual_goal="",
                template_id="split-left", status=PageStatus.READY,
            )

            metadata = engine._compose(
                base_path=base,
                text_path=text,
                output_path=composed,
                page=page,
                product_bbox=engine._product_box("split-left", 2048, 2048),
            )

            self.assertGreaterEqual(metadata["title_font_size"], 100)
            self.assertGreaterEqual(metadata["body_font_size"], 50)
            self.assertEqual("#181F1C", metadata["text_color"])
            self.assertTrue(text.exists())

    def test_review_plan_keeps_copy_exact_and_delegates_copy_check_to_ocr(self) -> None:
        profile = ProductProfile(
            sku="TEST", name="测试商品", category="洗衣机", model="",
            selling_points=(), parameters={},
        )
        page = PageItem(
            id="page-review", order=1, page_type=PageType.HERO,
            title="测试商品", body="专业呵护每一次使用", visual_goal="商品清晰",
            template_id="hero-center", status=PageStatus.READY,
        )

        with tempfile.TemporaryDirectory() as directory:
            engine = LocalProductionEngine(Path(directory), RepairingGenerator(), QualityStub())
            prompt = engine._content_review_prompt(profile, page)
            plan = engine._build_review_plan(profile, page, [Path("reference.png")])
        llm_requirements = " ".join(
            [*plan["must_appear"], *plan["must_not_appear"], *plan["must_preserve"], *plan["review_checks"]]
        )

        self.assertIn('"body": "专业呵护每一次使用"', prompt)
        self.assertEqual("专业呵护每一次使用", plan["authoritative_copy"]["body"])
        self.assertNotIn("专业呵护每一次使用。", prompt)
        self.assertNotIn("专业呵护每一次使用", llm_requirements)
        self.assertEqual("deterministic_ocr", plan["composition_evidence"]["copy_review_owner"])


if __name__ == "__main__":
    unittest.main()
