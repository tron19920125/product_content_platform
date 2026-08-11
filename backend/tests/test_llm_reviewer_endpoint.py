from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from PIL import Image

from product_content_platform.quality.llm_reviewer import (
    ReviewEvidence,
    _is_responses_endpoint,
    build_review_messages,
    default_review_endpoint,
)


class LlmReviewerEndpointTest(unittest.TestCase):
    def test_review_messages_include_every_product_reference_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = [root / "front.png", root / "detail.png"]
            for path in references:
                Image.new("RGB", (16, 16), "white").save(path)

            messages = build_review_messages(
                ReviewEvidence(
                    mode="generate",
                    user_prompt="综合参考图生成商品",
                    product_reference_image_paths=[str(path) for path in references],
                )
            )

        content = messages[1]["content"]
        image_parts = [part for part in content if part.get("type") == "image_url"]
        self.assertEqual(2, len(image_parts))
        self.assertIn("共 2 张", " ".join(str(part.get("text", "")) for part in content))

    def test_foundry_project_endpoint_uses_v1_responses_api(self) -> None:
        endpoint = default_review_endpoint(
            "https://example.services.ai.azure.com/api/projects/demo",
        )

        self.assertEqual(
            "https://example.services.ai.azure.com/api/projects/demo/openai/v1/responses",
            endpoint,
        )
        self.assertTrue(_is_responses_endpoint(endpoint))

    def test_explicit_preview_v1_endpoint_is_detected_as_responses_api(self) -> None:
        endpoint = "https://example.openai.azure.com/openai/v1/responses?api-version=preview"

        self.assertTrue(_is_responses_endpoint(endpoint))


if __name__ == "__main__":
    unittest.main()
