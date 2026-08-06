from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from product_content_platform.domain import ProductProfile


class LocalBaseImageGenerator:
    """Deterministic local adapter used for offline production and regression tests."""

    _palettes = ((25, 48, 39), (42, 52, 63), (83, 65, 55))

    def generate(
        self,
        *,
        prompt: str,
        profile: ProductProfile,
        reference_paths: list[Path],
        output_path: Path,
        variant: int,
    ) -> dict[str, Any]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = 900, 1200
        base_color = self._palettes[(variant - 1) % len(self._palettes)]
        canvas = Image.new("RGB", (width, height), base_color)
        draw = ImageDraw.Draw(canvas)
        for y in range(height):
            factor = 1 + (y / height) * 0.28
            color = tuple(min(255, int(channel * factor)) for channel in base_color)
            draw.line((0, y, width, y), fill=color)

        if "split-right" in prompt:
            product_box = (65, 225, 445, 1090)
        elif "hero-center" in prompt:
            product_box = (260, 350, 640, 1090)
        else:
            product_box = (455, 225, 835, 1090)
        source_used = ""
        reference = next((path for path in reference_paths if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}), None)
        if reference:
            source_used = str(reference)
            source = Image.open(reference).convert("RGB")
            source = ImageEnhance.Contrast(source).enhance(1.04)
            fitted = ImageOps.contain(source, (product_box[2] - product_box[0], product_box[3] - product_box[1]))
            x = product_box[0] + (product_box[2] - product_box[0] - fitted.width) // 2
            y = product_box[1] + (product_box[3] - product_box[1] - fitted.height) // 2
            shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            shadow_draw.rounded_rectangle((x + 14, y + 18, x + fitted.width + 14, y + fitted.height + 18), 20, fill=(0, 0, 0, 90))
            shadow = shadow.filter(ImageFilter.GaussianBlur(18))
            canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow).convert("RGB")
            canvas.paste(fitted, (x, y))
            product_box = (x, y, x + fitted.width, y + fitted.height)
        else:
            draw = ImageDraw.Draw(canvas)
            draw.rounded_rectangle(product_box, 34, fill=(220, 225, 221), outline=(247, 250, 248), width=8)
            cx = (product_box[0] + product_box[2]) // 2
            draw.ellipse((cx - 118, 350, cx + 118, 586), fill=(102, 115, 107), outline=(244, 247, 245), width=10)
            draw.ellipse((cx - 87, 381, cx + 87, 555), fill=(45, 58, 51))
            draw.rounded_rectangle((product_box[0] + 42, 920, product_box[2] - 42, 948), 8, fill=(112, 124, 117))

        canvas.save(output_path, format="PNG")
        return {
            "provider": "local-preview",
            "source_reference": source_used,
            "product_bbox": list(product_box),
            "prompt_chars": len(prompt),
        }


class AzureImageGenerator:
    """Azure image-generation adapter owned by the platform."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        # The optional path remains accepted to avoid breaking local callers; it is not used.
        _ = workspace_root

    def generate(
        self,
        *,
        prompt: str,
        profile: ProductProfile,
        reference_paths: list[Path],
        output_path: Path,
        variant: int,
    ) -> dict[str, Any]:
        from product_content_platform.integrations.azure_image_client import edit_image, generate_image

        token = os.environ.get("AZURE_OPENAI_BEARER_TOKEN", "")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if reference_paths:
            result = edit_image(
                prompt=prompt,
                reference_image_path=reference_paths[0],
                additional_reference_paths=reference_paths[1:3],
                output_dir=output_path.parent,
                bearer_token=token,
                quality=os.environ.get("PCP_IMAGE_QUALITY", "low"),
            )
        else:
            result = generate_image(
                prompt=prompt,
                output_dir=output_path.parent,
                bearer_token=token,
                quality=os.environ.get("PCP_IMAGE_QUALITY", "low"),
            )
        shutil.copyfile(result.image_path, output_path)
        with Image.open(output_path) as image:
            width, height = image.size
        return {
            "provider": "azure-gpt-image",
            "source_reference": str(reference_paths[0]) if reference_paths else "",
            "product_bbox": [int(width * .52), int(height * .18), int(width * .94), int(height * .92)],
            "elapsed_seconds": result.elapsed_seconds,
            "usage": result.usage,
        }
