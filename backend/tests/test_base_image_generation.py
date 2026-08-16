from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from product_content_platform.adapters.base_image_generation import AzureImageGenerator
from product_content_platform.domain import ProductProfile
from product_content_platform.integrations.azure_image_client import AzureImageGenerationError


class AzureImageGeneratorTest(unittest.TestCase):
    def test_icon_pack_keys_white_background_when_deployment_rejects_native_transparency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider_image = root / "provider.png"
            image = Image.new("RGB", (1024, 1024), "white")
            for x in range(250, 775):
                for y in range(350, 675):
                    image.putpixel((x, y), (30, 80, 60))
            image.save(provider_image)
            output = root / "icon-pack.png"
            with (
                patch.dict(
                    os.environ,
                    {
                        "AZURE_OPENAI_API_KEY": "test-key",
                        "AZURE_OPENAI_IMAGE_ENDPOINT": "https://example.test/images/generations",
                    },
                    clear=False,
                ),
                patch(
                    "product_content_platform.integrations.azure_credentials.token_provider_from_env",
                    return_value=None,
                ),
                patch(
                    "product_content_platform.integrations.azure_image_client.generate_image",
                    side_effect=[
                        AzureImageGenerationError('invalid_value: "background" Transparent background is not supported for this model.'),
                        SimpleNamespace(image_path=provider_image, elapsed_seconds=1, usage={}),
                    ],
                ) as generation,
            ):
                metadata = AzureImageGenerator().generate_icon_pack(
                    prompt="three coherent icons", concepts=["clean", "care", "energy"],
                    output_path=output, size="1024x1024", quality="medium",
                )
            with Image.open(output) as generated:
                alpha = generated.convert("RGBA").getchannel("A").getextrema()
            self.assertEqual(2, generation.call_count)
            self.assertIsNone(generation.call_args.kwargs.get("background"))
            self.assertEqual("light_background_keyed", metadata["transparency_method"])
            self.assertLess(alpha[0], 255)

    def test_model_edit_sends_all_selected_references_and_records_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = []
            for index in range(5):
                path = root / f"reference-{index}.png"
                Image.new("RGB", (64, 64), (20 + index, 30, 40)).save(path)
                references.append(path)
            provider_image = root / "provider.png"
            Image.new("RGB", (1024, 1024), "#dedbd5").save(provider_image)
            output = root / "candidate" / "base.png"

            with (
                patch.dict(
                    os.environ,
                    {
                        "AZURE_OPENAI_API_KEY": "test-key",
                        "AZURE_OPENAI_IMAGE_EDIT_ENDPOINT": "https://example.test/openai/v1/images/edits",
                        "PCP_MAX_IMAGE_REFERENCES": "6",
                    },
                    clear=False,
                ),
                patch(
                    "product_content_platform.integrations.azure_credentials.token_provider_from_env",
                    return_value=None,
                ),
                patch(
                    "product_content_platform.integrations.azure_image_client.edit_image",
                    return_value=SimpleNamespace(
                        image_path=provider_image,
                        elapsed_seconds=1.25,
                        usage={"input_tokens_details": {"image_tokens": 123}},
                    ),
                ) as edit_mock,
            ):
                metadata = AzureImageGenerator().generate(
                    prompt="综合全部参考图，在场景中重新生成同一商品。",
                    profile=ProductProfile(sku="X1", name="测试商品", category="家电"),
                    reference_paths=references,
                    output_path=output,
                    variant=1,
                    size="1024x1024",
                    quality="high",
                    layout={"product_box": (.25, .3, .9, .95)},
                    reference_strategy="model_edit",
                )

            call = edit_mock.call_args.kwargs
            self.assertEqual(references[0], call["reference_image_path"])
            self.assertEqual(references[1:], call["additional_reference_paths"])
            self.assertEqual("high", call["input_fidelity"])
            self.assertEqual(5, metadata["reference_count"])
            self.assertEqual([str(path) for path in references], metadata["source_references"])
            self.assertTrue(metadata["product_generated_by_model"])
            self.assertEqual("model_generated_target_region", metadata["product_bbox_source"])
            self.assertFalse(metadata["product_layer_file"])
            self.assertTrue(output.exists())

    def test_reference_limit_is_explicit_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = []
            for index in range(4):
                path = root / f"reference-{index}.png"
                Image.new("RGB", (32, 32), "white").save(path)
                references.append(path)
            provider_image = root / "provider.png"
            Image.new("RGB", (1024, 1024), "white").save(provider_image)

            with (
                patch.dict(
                    os.environ,
                    {
                        "AZURE_OPENAI_API_KEY": "test-key",
                        "AZURE_OPENAI_IMAGE_EDIT_ENDPOINT": "https://example.test/openai/v1/images/edits",
                        "PCP_MAX_IMAGE_REFERENCES": "2",
                    },
                    clear=False,
                ),
                patch(
                    "product_content_platform.integrations.azure_credentials.token_provider_from_env",
                    return_value=None,
                ),
                patch(
                    "product_content_platform.integrations.azure_image_client.edit_image",
                    return_value=SimpleNamespace(image_path=provider_image, elapsed_seconds=1, usage={}),
                ) as edit_mock,
            ):
                metadata = AzureImageGenerator().generate(
                    prompt="生成商品",
                    profile=ProductProfile(sku="X1", name="测试商品", category="家电"),
                    reference_paths=references,
                    output_path=root / "output.png",
                    variant=1,
                    size="1024x1024",
                    quality="high",
                    layout={},
                    reference_strategy="model_edit",
                )

            self.assertEqual([references[1]], edit_mock.call_args.kwargs["additional_reference_paths"])
            self.assertEqual(2, metadata["reference_count"])
            self.assertEqual(2, metadata["omitted_reference_count"])


if __name__ == "__main__":
    unittest.main()
