from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from product_content_platform.adapters.quality_toolkit import ProductQualityToolkit


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
        toolkit._read_image_text = lambda path: [
            toolkit._ocr_line(text="智能护理 容量12kg", confidence=.99, bbox=(.1, .1, .5, .3))
        ]
        toolkit._review_image_with_llm = lambda evidence: _Payload(
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


if __name__ == "__main__":
    unittest.main()
