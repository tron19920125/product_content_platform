from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from product_content_platform.adapters.quality_toolkit import ProductQualityToolkit
from product_content_platform.quality.azure_vision_ocr import AzureVisionOcrError
from product_content_platform.quality.llm_reviewer import LlmReviewerError, parse_llm_review_response
from product_content_platform.quality.text_review import OcrLine, TextReviewSpec, review_text_ocr


class _Payload:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return self._payload


class ProductQualityToolkitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_root = Path(__file__).resolve().parents[3]

    def test_local_mode_uses_deterministic_text_layer_evidence(self) -> None:
        toolkit = ProductQualityToolkit(self.workspace_root, mode="local")

        result = toolkit.review_candidate(
            output_path=Path("unused.png"),
            reference_path=None,
            prompt="测试",
            review_plan={},
            visual_review={},
            generation={},
            title="智能护理",
            body="容量12kg",
            bbox=(.1, .1, .5, .3),
            number_allowlist=["12kg"],
        )

        self.assertEqual("text-layer", result["provider"])
        self.assertEqual("pass", result["text_review"]["status"])
        self.assertEqual({}, result["llm_review"])

    def test_platform_source_has_no_legacy_package_imports(self) -> None:
        source_root = Path(__file__).resolve().parents[1] / "src"
        forbidden: list[str] = []
        for source_path in source_root.rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            for node in ast.walk(tree):
                module = node.module if isinstance(node, ast.ImportFrom) else ""
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
                if module.startswith("image_qa_mvp") or any(name.startswith("image_qa_mvp") for name in names):
                    forbidden.append(str(source_path.relative_to(source_root)))

        self.assertEqual([], forbidden)
        self.assertFalse((source_root / "image_qa_mvp").exists())

    def test_azure_mode_connects_real_ocr_plan_and_multimodal_seams(self) -> None:
        toolkit = ProductQualityToolkit(self.workspace_root, mode="azure")
        toolkit._create_review_plan = lambda *args, **kwargs: _Payload({"source": "llm", "requirements": []})
        toolkit._read_image_text = lambda path, **kwargs: [
            toolkit._ocr_line(text="智能护理 容量12kg", confidence=.99, bbox=(.1, .1, .5, .3))
        ]
        toolkit._review_image_with_llm = lambda evidence, **kwargs: _Payload(
            {"status": "pass", "issues": [], "score_breakdown": {"text_accuracy": 100}}
        )

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "candidate.png"
            Image.new("RGB", (10, 10), "white").save(image_path)
            plan = toolkit.review_plan("测试提示词", reference_path=image_path)
            result = toolkit.review_candidate(
                output_path=image_path,
                reference_path=image_path,
                prompt="测试提示词",
                review_plan=plan,
                visual_review={"status": "pass"},
                generation={"provider": "test"},
                title="智能护理",
                body="容量12kg",
                bbox=(.1, .1, .5, .3),
                number_allowlist=["12kg"],
            )

        self.assertEqual("llm", plan["source"])
        self.assertEqual("azure-ai-vision+azure-openai", result["provider"])
        self.assertEqual("pass", result["text_review"]["status"])
        self.assertEqual("pass", result["llm_review"]["status"])

    def test_number_allowlist_only_checks_post_composed_copy_region(self) -> None:
        result = review_text_ocr(
            [
                OcrLine(text="测试商品", confidence=.99, bbox=(.08, .08, .35, .15)),
                OcrLine(text="专业呵护", confidence=.99, bbox=(.08, .17, .35, .21)),
                OcrLine(text="36", confidence=.99, bbox=(.65, .40, .70, .43)),
            ],
            TextReviewSpec(
                required_text=["测试商品", "专业呵护"],
                number_allowlist=[],
                strict_number_allowlist=True,
                expected_text_region=(.05, .05, .50, .30),
            ),
        )

        self.assertEqual("pass", result.status)
        self.assertEqual([], result.extracted_numbers)
        self.assertEqual("expected_text_region", result.checked["number_scope"])

    def test_required_copy_tolerates_ocr_line_break_and_dropped_punctuation(self) -> None:
        result = review_text_ocr(
            [
                OcrLine(text="静谧洗护", confidence=.99, bbox=(.08, .08, .35, .15)),
                OcrLine(text="自成风景", confidence=.99, bbox=(.08, .16, .35, .23)),
            ],
            TextReviewSpec(
                required_text=["静谧洗护，自成风景"],
                expected_text_region=(.05, .05, .50, .30),
            ),
        )

        self.assertEqual("pass", result.status)
        self.assertEqual([], result.issues)

    def test_number_allowlist_still_rejects_unapproved_copy_number_inside_region(self) -> None:
        result = review_text_ocr(
            [OcrLine(text="专业呵护 36", confidence=.99, bbox=(.08, .17, .35, .21))],
            TextReviewSpec(
                required_text=["专业呵护"],
                number_allowlist=[],
                strict_number_allowlist=True,
                expected_text_region=(.05, .05, .50, .30),
            ),
        )

        self.assertEqual("fail", result.status)
        self.assertEqual(["36"], result.extracted_numbers)

    def test_number_allowlist_preserves_confirmed_number_with_unit(self) -> None:
        result = review_text_ocr(
            [OcrLine(text="容量 12kg", confidence=.99, bbox=(.08, .17, .35, .21))],
            TextReviewSpec(
                required_text=["容量 12kg"],
                number_allowlist=["12kg"],
                strict_number_allowlist=True,
                expected_text_region=(.05, .05, .50, .30),
            ),
        )

        self.assertEqual("pass", result.status)
        self.assertEqual(["12kg"], result.extracted_numbers)

    def test_llm_review_drops_unplanned_requirements_and_uses_plan_verdict(self) -> None:
        result = parse_llm_review_response(
            {
                "status": "fail",
                "review_items": [
                    {
                        "requirement_id": "appear-001",
                        "category": "layout_position",
                        "severity": "P3",
                        "result": "pass",
                        "expected": "模型改写的要求",
                        "message": "布局符合要求",
                    },
                    {
                        "requirement_id": "invented-001",
                        "category": "text_accuracy",
                        "severity": "P1",
                        "result": "fail",
                        "message": "正文缺少模型自行添加的句号",
                    },
                ],
            },
            requirements=[
                {"id": "appear-001", "type": "must_appear", "label": "必须出现", "text": "商品完整显示"}
            ],
        )

        self.assertEqual("pass", result.status)
        self.assertEqual([], result.issues)
        self.assertEqual("商品完整显示", result.review_items[0]["expected"])

    def test_reserved_area_detects_model_generated_copy(self) -> None:
        toolkit = ProductQualityToolkit(self.workspace_root, mode="azure")
        toolkit._read_image_text = lambda path, **kwargs: [
            toolkit._ocr_line(text="错误标题", confidence=.99, bbox=(.1, .1, .4, .2)),
            toolkit._ocr_line(text="商品面板", confidence=.99, bbox=(.7, .5, .9, .6)),
        ]

        result = toolkit.inspect_reserved_area(Path("unused.png"), (.05, .05, .5, .4))

        self.assertEqual(2, len(result["lines"]))
        self.assertEqual(["错误标题"], [row["text"] for row in result["unexpected_lines"]])

    def test_azure_mode_preserves_candidate_when_llm_review_is_unavailable(self) -> None:
        toolkit = ProductQualityToolkit(self.workspace_root, mode="azure")
        toolkit._read_image_text = lambda path, **kwargs: [
            toolkit._ocr_line(text="测试商品", confidence=.99, bbox=(.1, .1, .5, .3))
        ]

        def unavailable(*args, **kwargs):
            raise LlmReviewerError("SSL connection closed")

        toolkit._review_image_with_llm = unavailable

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "candidate.png"
            Image.new("RGB", (10, 10), "white").save(image_path)
            result = toolkit.review_candidate(
                output_path=image_path,
                reference_path=None,
                prompt="测试提示词",
                review_plan={},
                visual_review={},
                generation={"provider": "test"},
                title="测试商品",
                body="",
                bbox=(.1, .1, .5, .3),
                number_allowlist=[],
            )

        self.assertEqual("review", result["llm_review"]["status"])
        self.assertTrue(result["llm_review"]["degraded"])
        self.assertEqual("review_unavailable", result["llm_review"]["issues"][0]["code"])

    def test_azure_mode_falls_back_when_review_plan_llm_is_unavailable(self) -> None:
        toolkit = ProductQualityToolkit(self.workspace_root, mode="azure")

        def unavailable(*args, **kwargs):
            raise LlmReviewerError("SSL connection closed")

        toolkit._create_review_plan = unavailable
        result = toolkit.review_plan("生成一张商品主图")

        self.assertEqual("fallback", result["source"])
        self.assertTrue(result["degraded"])
        self.assertIn("SSL connection closed", result["error"])

    def test_azure_mode_preserves_candidate_when_ocr_is_unavailable(self) -> None:
        toolkit = ProductQualityToolkit(self.workspace_root, mode="azure")

        def unavailable(*args, **kwargs):
            raise AzureVisionOcrError("Azure CLI unavailable")

        toolkit._read_image_text = unavailable
        toolkit._review_image_with_llm = lambda evidence, **kwargs: _Payload(
            {"status": "pass", "issues": []}
        )

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "candidate.png"
            Image.new("RGB", (10, 10), "white").save(image_path)
            result = toolkit.review_candidate(
                output_path=image_path,
                reference_path=None,
                prompt="测试提示词",
                review_plan={},
                visual_review={},
                generation={"provider": "test"},
                title="测试商品",
                body="专业呵护",
                bbox=(.1, .1, .5, .3),
                number_allowlist=[],
            )

        self.assertEqual("text-layer-fallback+azure-openai", result["provider"])
        self.assertEqual("review", result["llm_review"]["status"])
        self.assertTrue(result["llm_review"]["degraded"])
        self.assertEqual("ocr_unavailable", result["llm_review"]["issues"][0]["code"])


if __name__ == "__main__":
    unittest.main()
