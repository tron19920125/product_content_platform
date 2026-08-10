from __future__ import annotations

import unittest

from product_content_platform.quality.llm_reviewer import (
    _is_responses_endpoint,
    default_review_endpoint,
)


class LlmReviewerEndpointTest(unittest.TestCase):
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
