from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from product_content_platform.adapters.base_image_generation import _composite_reference_product
from product_content_platform.adapters.production_engine import LocalProductionEngine
from product_content_platform.domain import (
    Candidate,
    CandidateStatus,
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
        self.layouts: list[dict] = []
        self.reference_strategies: list[str] = []

    def generate(self, *, prompt, profile, reference_paths, output_path, variant, size, quality, layout, reference_strategy):
        self.calls += 1
        self.prompts.append(prompt)
        self.layouts.append(layout)
        self.reference_strategies.append(reference_strategy)
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
                prompt_version_id=prompt.id, model="repair-test",
                model_params={"max_auto_regenerations": 1},
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
            self.assertEqual("ai", result.metadata["composition"]["text_document_source"])
            self.assertEqual(
                {"headline", "body"},
                {layer["role"] for layer in result.metadata["composition"]["text_layers"]},
            )

    def test_ai_layout_returns_a_visible_alternative_and_honors_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.png"
            Image.new("RGB", (1200, 800), "white").save(base)
            engine = LocalProductionEngine(root / "production", RepairingGenerator(), QualityStub())
            page = PageItem(
                id="ai-layout", order=1, page_type=PageType.HERO,
                title="向上生长", body="让专业护理融入理想生活", visual_goal="高端生活场景",
                template_id="hero-center", status=PageStatus.READY,
            )
            candidate = Candidate(
                id="candidate-layout", job_id="job-layout", project_id="project-layout",
                page_id=page.id, candidate_index=1, base_path="base.png",
                text_layer_path="text.png", composed_path="composed.png", prompt="",
                score=0, rank=1, status=CandidateStatus.GENERATED,
            )
            engine._root = root.resolve()

            initial = engine.suggest_text_document(candidate=candidate, page=page)
            alternative = engine.suggest_text_document(candidate=candidate, page=page, current=initial)
            traditional = engine.suggest_text_document(
                candidate=candidate, page=page, current=alternative,
                instruction="国风书法标题，正文居中克制",
            )

            self.assertNotEqual(
                [(layer.font_family, layer.font_size, layer.text_align) for layer in initial.layers],
                [(layer.font_family, layer.font_size, layer.text_align) for layer in alternative.layers],
            )
            headline = next(layer for layer in traditional.layers if layer.role == "headline")
            self.assertEqual("ma-shan-zheng", headline.font_family)
            self.assertEqual("center", headline.text_align)
            self.assertIn("东方书写", traditional.ai_reasoning)

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

    def test_text_contrast_samples_rendered_copy_instead_of_the_full_reserved_box(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.png"
            image = Image.new("RGB", (2048, 2048), "#101010")
            # The copy sits on this light wall, while the unused right side of
            # the wide hero reservation remains dark like a cabinet.
            ImageDraw.Draw(image).rectangle((0, 0, 900, 700), fill="white")
            image.save(base)
            engine = LocalProductionEngine(root / "production", RepairingGenerator(), QualityStub())
            page = PageItem(
                id="localized-contrast", order=1, page_type=PageType.HERO,
                title="高端洗护", body="10kg 大容量", visual_goal="",
                template_id="hero-center", status=PageStatus.READY,
            )

            metadata = engine._compose(
                base_path=base,
                text_path=root / "text.png",
                output_path=root / "composed.png",
                page=page,
                product_bbox=engine._product_box("hero-center", 2048, 2048),
            )

            self.assertEqual("#181F1C", metadata["text_color"])
            self.assertGreaterEqual(metadata["background_luminance"], 200)
            self.assertLess(metadata["color_sample_box"][2], 900)

    def test_subjective_llm_findings_cannot_become_release_blockers(self) -> None:
        self.assertEqual("P2", LocalProductionEngine._llm_issue_severity("layout_position", "P1"))
        self.assertEqual("P2", LocalProductionEngine._llm_issue_severity("visual_quality", "P0"))
        self.assertEqual("P1", LocalProductionEngine._llm_issue_severity("reference_consistency", "P1"))
        self.assertEqual("P1", LocalProductionEngine._llm_issue_severity("text_accuracy", "P1"))

    def test_generation_prompt_removes_copy_without_leaving_empty_parentheses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = LocalProductionEngine(Path(directory), RepairingGenerator(), QualityStub())
            profile = ProductProfile(
                sku="WM-01", name="高端洗衣机", category="洗衣机", model="TG10EK60",
            )
            page = PageItem(
                id="model-copy", order=1, page_type=PageType.PARAMETERS,
                title="TG10EK60", body="10kg 大容量", visual_goal="高端洗护空间",
                template_id="data-grid", status=PageStatus.READY,
            )
            body = "为{{product_name}}（{{model}}）制作{{category}}场景，{{visual_goal}}。"

            prompt = engine._bind_generation_prompt(
                body, profile, page, reference_strategy="layered_product",
            )

            self.assertNotIn(page.title, prompt)
            self.assertNotIn(page.body, prompt)
            self.assertNotIn("（）", prompt)

    def test_title_fitting_avoids_two_character_orphan_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = LocalProductionEngine(Path(directory), RepairingGenerator(), QualityStub())
            image = Image.new("RGB", (2048, 2048), "white")
            draw = ImageDraw.Draw(image)

            root = Path(directory)
            base = root / "base.png"
            Image.new("RGB", (2048, 2048), "white").save(base)
            page = PageItem(
                id="balanced-title", order=1, page_type=PageType.SCENE,
                title="静谧洗护，自成风景",
                body="自然光、温润木饰面与石材地面，共同构成真实而高级的家庭洗护空间。",
                visual_goal="", template_id="scene-overlay", heading_level=2,
                status=PageStatus.READY,
            )
            metadata = engine._compose(
                base_path=base,
                text_path=root / "text.png",
                output_path=root / "composed.png",
                page=page,
                product_bbox=engine._product_box("scene-overlay", 2048, 2048),
            )

            lines = metadata["title_lines"]
            self.assertEqual(["静谧洗护，", "自成风景"], lines)

    def test_layered_product_prompt_and_composition_preserve_reference_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            background = root / "background.png"
            reference = root / "reference.png"
            output = root / "base.png"
            Image.new("RGB", (400, 400), "#d8c9b6").save(background)
            product = Image.new("RGB", (240, 240), "white")
            product_draw = ImageDraw.Draw(product)
            product_draw.rectangle((50, 30, 190, 220), fill="#101820")
            product.save(reference)

            bbox = _composite_reference_product(
                background_path=background,
                reference_path=reference,
                output_path=output,
                target_box=(80, 100, 360, 380),
            )

            self.assertTrue(output.exists())
            self.assertTrue((root / "product_layer.png").exists())
            self.assertGreater(bbox[0], 80)
            self.assertLess(bbox[2], 360)
            with Image.open(root / "product_layer.png") as layer:
                self.assertEqual(0, layer.getpixel((0, 0))[3])
                self.assertGreater(layer.getpixel(((bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2))[3], 200)

            engine = LocalProductionEngine(root / "production", RepairingGenerator(), QualityStub())
            page = PageItem(
                id="page-layer", order=1, page_type=PageType.SCENE,
                title="静谧洗护", body="自然融入生活", visual_goal="高端洗衣房",
                template_id="scene-overlay", status=PageStatus.READY,
            )
            profile = ProductProfile(sku="L1", name="滚筒洗衣机", category="洗衣机")
            prompt = engine._bind_generation_prompt(
                "生成{{visual_goal}}的场景。{{composition_instruction}}。",
                profile,
                page,
                reference_strategy="layered_product",
            )
            self.assertIn("只生成空置场景底图", prompt)
            self.assertIn("不要生成、绘制、复制或暗示任何商品", prompt)
            self.assertNotIn(page.title, prompt)

    def test_scene_layout_separates_anchor_from_allowed_open_door_extent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = LocalProductionEngine(Path(directory), RepairingGenerator(), QualityStub())
            extent = engine._product_box("scene-overlay", 1000, 1000)
            anchor = engine._product_anchor_box("scene-overlay", 1000, 1000)
            text_box = engine._text_box("scene-overlay", 1000, 1000)

        self.assertLess(extent[0], anchor[0])
        self.assertGreaterEqual(extent[1], text_box[3])
        self.assertIn("延展结构", engine._layout_spec("scene-overlay")["instruction"])

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
