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
        layout: dict[str, Any],
        reference_strategy: str,
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

        product_box = _scaled_box(layout.get("product_box") or (.20, .32, .80, .94), width, height)
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
            "source_references": [str(path) for path in reference_paths],
            "reference_count": len(reference_paths),
            "product_bbox": list(product_box),
            "prompt_chars": len(prompt),
            "requested_size": size,
            "actual_size": f"{width}x{height}",
            "quality": quality,
            "reference_strategy": reference_strategy,
            "product_bbox_source": "deterministic_composite",
            "product_generated_by_model": False,
            "local_reference_emulation": bool(reference_paths),
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
        layout: dict[str, Any],
        reference_strategy: str,
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
        valid_reference_paths = [
            path for path in reference_paths
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ]
        reference_limit = _reference_limit()
        selected_reference_paths = valid_reference_paths[:reference_limit]
        configured_generation_endpoint = os.environ.get("AZURE_OPENAI_IMAGE_ENDPOINT", "")
        layered_reference = bool(selected_reference_paths) and reference_strategy == "layered_product"
        if selected_reference_paths and not layered_reference:
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
        if selected_reference_paths and not layered_reference:
            result = edit_image(
                prompt=prompt,
                reference_image_path=selected_reference_paths[0],
                additional_reference_paths=selected_reference_paths[1:],
                output_dir=output_path.parent,
                bearer_token=token,
                api_key=api_key,
                token_provider=token_provider,
                endpoint=image_endpoint,
                quality=quality,
                size=size,
                input_fidelity="high",
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
        product_bbox: list[int] | None = None
        product_bbox_source = "unavailable"
        if layered_reference:
            background_path = output_path.parent / "background.png"
            shutil.copyfile(output_path, background_path)
            product_bbox = list(
                _composite_reference_product(
                    background_path=background_path,
                    reference_path=selected_reference_paths[0],
                    output_path=output_path,
                    target_box=_scaled_box(layout.get("product_box") or (.20, .32, .80, .94), width, height),
                )
            )
            product_bbox_source = "layered_reference"
        elif selected_reference_paths:
            product_bbox = list(
                _scaled_box(layout.get("product_box") or (.20, .32, .80, .94), width, height)
            )
            product_bbox_source = "model_generated_target_region"
        metadata = {
            "provider": "azure-gpt-image",
            "source_reference": str(selected_reference_paths[0]) if selected_reference_paths else "",
            "source_references": [str(path) for path in selected_reference_paths],
            "reference_count": len(selected_reference_paths),
            "reference_limit": reference_limit,
            "omitted_reference_count": max(0, len(valid_reference_paths) - len(selected_reference_paths)),
            "input_fidelity": "high" if selected_reference_paths else "",
            "elapsed_seconds": result.elapsed_seconds,
            "usage": result.usage,
            "requested_size": size,
            "actual_size": f"{width}x{height}",
            "quality": quality,
            "reference_strategy": "layered_product" if layered_reference else ("model_edit" if selected_reference_paths else "text_to_image"),
            "product_bbox_source": product_bbox_source,
            "product_generated_by_model": bool(selected_reference_paths and not layered_reference),
            "background_file": "background.png" if layered_reference else "",
            "product_layer_file": "product_layer.png" if layered_reference else "",
        }
        if product_bbox is not None:
            metadata["product_bbox"] = product_bbox
        return metadata


def _reference_limit() -> int:
    try:
        configured = int(os.environ.get("PCP_MAX_IMAGE_REFERENCES", "6"))
    except ValueError:
        configured = 6
    return max(1, min(16, configured))


def _scaled_box(values: Any, width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = (float(value) for value in values)
    return int(width * x1), int(height * y1), int(width * x2), int(height * y2)


def _composite_reference_product(
    *,
    background_path: Path,
    reference_path: Path,
    output_path: Path,
    target_box: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    background = Image.open(background_path).convert("RGBA")
    max_width = max(1, target_box[2] - target_box[0])
    max_height = max(1, target_box[3] - target_box[1])
    source = Image.open(reference_path).convert("RGBA")
    if source.width > max_width or source.height > max_height:
        source = ImageOps.contain(source, (max_width, max_height), Image.Resampling.LANCZOS)
    product = _remove_connected_light_background(source)
    product = ImageOps.contain(product, (max_width, max_height), Image.Resampling.LANCZOS)
    x = target_box[0] + (max_width - product.width) // 2
    y = target_box[3] - product.height

    layer = Image.new("RGBA", background.size, (0, 0, 0, 0))
    layer.alpha_composite(product, (x, y))
    layer.save(output_path.parent / "product_layer.png", format="PNG")

    shadow_alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(max(6, min(background.size) // 120)))
    shifted_alpha = Image.new("L", background.size, 0)
    shadow_x = max(4, background.width // 256)
    shadow_y = max(6, background.height // 170)
    shifted_alpha.paste(
        shadow_alpha.crop((0, 0, background.width - shadow_x, background.height - shadow_y)),
        (shadow_x, shadow_y),
    )
    shadow = Image.new("RGBA", background.size, (0, 0, 0, 80))
    shadow.putalpha(shifted_alpha.point(lambda value: min(90, value // 3)))
    composed = Image.alpha_composite(Image.alpha_composite(background, shadow), layer)
    composed.convert("RGB").save(output_path, format="PNG")
    return x, y, x + product.width, y + product.height


def _remove_connected_light_background(image: Image.Image) -> Image.Image:
    existing_alpha = image.getchannel("A")
    if existing_alpha.getextrema()[0] < 250:
        bbox = existing_alpha.getbbox()
        return image.crop(bbox) if bbox else image

    marker = (255, 0, 255)
    flood = image.convert("RGB")
    for seed in ((0, 0), (flood.width - 1, 0), (0, flood.height - 1), (flood.width - 1, flood.height - 1)):
        ImageDraw.floodfill(flood, seed, marker, thresh=48)
    alpha = Image.new("L", flood.size, 255)
    pixels = flood.get_flattened_data() if hasattr(flood, "get_flattened_data") else flood.getdata()
    alpha.putdata([0 if pixel == marker else 255 for pixel in pixels])
    alpha = alpha.filter(ImageFilter.GaussianBlur(.7))
    image.putalpha(alpha)
    bbox = alpha.getbbox()
    return image.crop(bbox) if bbox else image
