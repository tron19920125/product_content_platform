from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from product_content_platform.domain import (
    ProductProfile,
    validate_image_quality,
    validate_image_size,
)


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
        size: str,
        quality: str,
    ) -> dict[str, Any]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = validate_image_size(size)
        quality = validate_image_quality(quality)
        base_color = self._palettes[(variant - 1) % len(self._palettes)]
        canvas = Image.new("RGB", (width, height), base_color)
        draw = ImageDraw.Draw(canvas)
        for y in range(height):
            factor = 1 + (y / height) * 0.28
            color = tuple(min(255, int(channel * factor)) for channel in base_color)
            draw.line((0, y, width, y), fill=color)

        # Deterministic scene cues keep the offline demo representative of the Azure workflow.
        horizon = int(height * .72)
        draw.rectangle((0, horizon, width, height), fill=tuple(min(255, channel + 30) for channel in base_color))
        draw.ellipse(
            (int(width * .58), int(height * .08), int(width * .94), int(height * .36)),
            fill=tuple(min(255, channel + 58) for channel in base_color),
        )
        draw.rounded_rectangle(
            (int(width * .72), int(height * .42), int(width * .88), int(height * .69)),
            max(12, width // 80),
            fill=tuple(min(255, channel + 42) for channel in base_color),
        )
        draw.ellipse(
            (int(width * .76), int(height * .35), int(width * .84), int(height * .48)),
            fill=(112, 139, 116),
        )

        if "商品主体完整放在左侧" in prompt:
            product_box = (int(width * .06), int(height * .16), int(width * .52), int(height * .94))
        elif "商品主体完整居中" in prompt or "下方中央" in prompt:
            product_box = (int(width * .20), int(height * .32), int(width * .80), int(height * .94))
        else:
            product_box = (int(width * .48), int(height * .16), int(width * .94), int(height * .94))
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
            radius = max(50, int((product_box[2] - product_box[0]) * .31))
            drum_y = product_box[1] + int((product_box[3] - product_box[1]) * .28)
            draw.ellipse(
                (cx - radius, drum_y - radius, cx + radius, drum_y + radius),
                fill=(102, 115, 107), outline=(244, 247, 245), width=max(6, width // 180),
            )
            inner = int(radius * .74)
            draw.ellipse((cx - inner, drum_y - inner, cx + inner, drum_y + inner), fill=(45, 58, 51))
            line_y = product_box[1] + int((product_box[3] - product_box[1]) * .83)
            draw.rounded_rectangle(
                (product_box[0] + int(radius * .35), line_y, product_box[2] - int(radius * .35), line_y + max(8, height // 90)),
                max(5, width // 140), fill=(112, 124, 117),
            )

        canvas.save(output_path, format="PNG")
        return {
            "provider": "local-preview",
            "source_reference": source_used,
            "product_bbox": list(product_box),
            "prompt_chars": len(prompt),
            "requested_size": size,
            "actual_size": f"{width}x{height}",
            "quality": quality,
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
        size: str,
        quality: str,
    ) -> dict[str, Any]:
        from product_content_platform.integrations.azure_image_client import (
            default_edit_endpoint,
            default_generation_endpoint,
            edit_image,
            generate_image,
            to_edit_endpoint,
        )
        from product_content_platform.integrations.azure_credentials import token_provider_from_env

        token = os.environ.get("AZURE_OPENAI_BEARER_TOKEN", "")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        requested_width, requested_height = validate_image_size(size)
        quality = validate_image_quality(quality)
        configured_generation_endpoint = os.environ.get("AZURE_OPENAI_IMAGE_ENDPOINT", "")
        if reference_paths:
            configured_edit_endpoint = os.environ.get("AZURE_OPENAI_IMAGE_EDIT_ENDPOINT", "")
            image_endpoint = (
                configured_edit_endpoint
                or (to_edit_endpoint(configured_generation_endpoint) if configured_generation_endpoint else "")
                or default_edit_endpoint()
            )
        else:
            image_endpoint = configured_generation_endpoint or default_generation_endpoint()
        token_provider = token_provider_from_env(endpoint=image_endpoint)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if reference_paths:
            result = edit_image(
                prompt=prompt,
                reference_image_path=reference_paths[0],
                additional_reference_paths=reference_paths[1:3],
                output_dir=output_path.parent,
                bearer_token=token,
                api_key=api_key,
                token_provider=token_provider,
                endpoint=image_endpoint,
                quality=quality,
                size=size,
            )
        else:
            result = generate_image(
                prompt=prompt,
                output_dir=output_path.parent,
                bearer_token=token,
                api_key=api_key,
                token_provider=token_provider,
                endpoint=image_endpoint,
                quality=quality,
                size=size,
            )
        shutil.copyfile(result.image_path, output_path)
        with Image.open(output_path) as image:
            width, height = image.size
        if (width, height) != (requested_width, requested_height):
            raise RuntimeError(
                f"Azure 返回尺寸与模板不一致：请求 {requested_width}x{requested_height}，实际 {width}x{height}"
            )
        return {
            "provider": "azure-gpt-image",
            "source_reference": str(reference_paths[0]) if reference_paths else "",
            "product_bbox": [int(width * .52), int(height * .18), int(width * .94), int(height * .92)],
            "elapsed_seconds": result.elapsed_seconds,
            "usage": result.usage,
            "requested_size": size,
            "actual_size": f"{width}x{height}",
            "quality": quality,
        }
