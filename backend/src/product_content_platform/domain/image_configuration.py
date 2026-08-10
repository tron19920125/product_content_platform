from __future__ import annotations

import re
from typing import Any

from .models import DomainValidationError


IMAGE_QUALITIES = ("low", "medium", "high")
MAX_IMAGE_PIXELS = 8_294_400
MIN_IMAGE_PIXELS = 655_360
MAX_IMAGE_EDGE = 3_840
MAX_ASPECT_RATIO = 3.0

IMAGE_SIZE_PRESETS: tuple[dict[str, Any], ...] = (
    {"value": "1024x1024", "label": "正方形标准", "note": "通用草稿与商品方图"},
    {"value": "1536x1024", "label": "横版标准", "note": "3:2 横版详情图"},
    {"value": "1024x1536", "label": "竖版标准", "note": "2:3 竖版详情图"},
    {"value": "2048x2048", "label": "正方形高清", "note": "正式商品图，平台默认"},
    {"value": "2048x1152", "label": "横版高清", "note": "16:9 横版"},
    {"value": "1152x2048", "label": "竖版高清", "note": "9:16 竖版"},
    {"value": "2560x1440", "label": "横版 2K", "note": "推荐可靠性上界"},
    {"value": "1440x2560", "label": "竖版 2K", "note": "推荐可靠性上界"},
    {
        "value": "2880x2880",
        "label": "最大正方形",
        "note": "达到 8,294,400 总像素上限",
        "experimental": True,
    },
    {"value": "3840x2160", "label": "横版 4K", "note": "实验性超高清", "experimental": True},
    {"value": "2160x3840", "label": "竖版 4K", "note": "实验性超高清", "experimental": True},
)


def validate_image_quality(value: str) -> str:
    quality = value.strip().lower()
    if quality not in IMAGE_QUALITIES:
        raise DomainValidationError(f"生成质量必须是：{', '.join(IMAGE_QUALITIES)}")
    return quality


def validate_image_size(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{2,4})x(\d{2,4})", value.strip().lower())
    if not match:
        raise DomainValidationError("尺寸格式必须为 宽x高，例如 2048x2048")
    width, height = (int(part) for part in match.groups())
    if width % 16 or height % 16:
        raise DomainValidationError("宽度和高度都必须是 16 的倍数")
    if max(width, height) > MAX_IMAGE_EDGE:
        raise DomainValidationError(f"最长边不能超过 {MAX_IMAGE_EDGE}px")
    if max(width, height) / min(width, height) > MAX_ASPECT_RATIO:
        raise DomainValidationError("最长边与最短边的比例不能超过 3:1")
    pixels = width * height
    if pixels < MIN_IMAGE_PIXELS or pixels > MAX_IMAGE_PIXELS:
        raise DomainValidationError(
            f"总像素必须在 {MIN_IMAGE_PIXELS:,} 到 {MAX_IMAGE_PIXELS:,} 之间"
        )
    return width, height


def image_capabilities() -> dict[str, Any]:
    return {
        "model": "gpt-image-2",
        "qualities": list(IMAGE_QUALITIES),
        "size_presets": [dict(item) for item in IMAGE_SIZE_PRESETS],
        "custom_size": {
            "multiple_of": 16,
            "max_edge": MAX_IMAGE_EDGE,
            "max_aspect_ratio": MAX_ASPECT_RATIO,
            "min_pixels": MIN_IMAGE_PIXELS,
            "max_pixels": MAX_IMAGE_PIXELS,
            "max_square": "2880x2880",
        },
    }
