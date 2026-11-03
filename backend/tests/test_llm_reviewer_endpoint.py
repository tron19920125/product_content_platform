from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from PIL import Image

from product_content_platform.quality.llm_reviewer import (
    ReviewEvidence,
    _build_responses_request,
    _is_responses_endpoint,
    build_review_messages,
    default_review_endpoint,
)


class LlmReviewerEndpointTest(unittest.TestCase):
    def test_json_mode_instruction_is_not_satisfied_by_image_encoding_or_url(self):
        for image_url in ['data:image/png;base64,AAAAjSoNAAAA', 'https://example.test/json/image.png']:
            with self.subTest(image_url=image_url):
                payload = _build_responses_request([
                    {'role':'system','content':'Return JSON matching the schema.'},
                    {'role':'user','content':[{'type':'text','text':'核验这张商品图'},
                                             {'type':'image_url','image_url':{'url':image_url}}]},
                ], model='test-model')
                parts = payload['input'][0]['content']
                visible_text = ' '.join(part.get('text','') for part in parts if part['type']=='input_text')
                self.assertIn('JSON', visible_text)
                self.assertIn({'type':'input_image','image_url':image_url}, parts)

    def test_existing_visible_json_instruction_is_preserved_without_duplication(self):
        payload = _build_responses_request([{'role':'user','content':'请返回 JSON。'}], model='test-model')
        self.assertEqual([{'type':'input_text','text':'请返回 JSON。'}], payload['input'][0]['content'])

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
