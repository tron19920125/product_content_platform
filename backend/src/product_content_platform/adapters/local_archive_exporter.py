from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageColor


class LocalArchiveExporter:
    """Creates traceable ZIP delivery packages below one controlled root."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        archive_name: str,
        files: dict[str, Path],
        documents: dict[str, object],
    ) -> Path:
        safe_name = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", archive_name).strip("_") or "export"
        target = self._root / f"{safe_name}_{uuid4().hex[:8]}.zip"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for archive_path, source in files.items():
                if source.exists() and source.is_file():
                    archive.write(source, archive_path)
            for archive_path, payload in documents.items():
                archive.writestr(archive_path, json.dumps(payload, ensure_ascii=False, indent=2))
        return target

    def resolve(self, file_name: str) -> Path:
        target = (self._root / Path(file_name).name).resolve()
        if target.parent != self._root or not target.exists():
            raise FileNotFoundError(file_name)
        return target

    def stitch(
        self,
        export_name: str,
        images: list[Path],
        *,
        direction: str,
        gap: int,
        background_color: str,
        alignment: str,
    ) -> Path:
        """Join full-resolution images without resampling and store a PNG export."""
        if len(images) < 2:
            raise ValueError("长图拼接至少需要选择 2 张图片")
        if direction not in {"vertical", "horizontal"}:
            raise ValueError("不支持的拼接方向")
        if alignment not in {"start", "center", "end"}:
            raise ValueError("不支持的图片对齐方式")
        try:
            background = ImageColor.getrgb(background_color)
        except ValueError as exc:
            raise ValueError("长图背景色必须是有效的十六进制颜色") from exc

        opened: list[Image.Image] = []
        try:
            opened = [Image.open(path).convert("RGB") for path in images]
            widths = [image.width for image in opened]
            heights = [image.height for image in opened]
            if direction == "vertical":
                canvas_size = (max(widths), sum(heights) + gap * (len(opened) - 1))
            else:
                canvas_size = (sum(widths) + gap * (len(opened) - 1), max(heights))
            if canvas_size[0] > 65535 or canvas_size[1] > 65535:
                raise ValueError("拼接后的长图单边不能超过 65535 像素")
            if canvas_size[0] * canvas_size[1] > 80_000_000:
                raise ValueError("拼接后的长图超过 8000 万像素，请减少图片数量或尺寸")

            canvas = Image.new("RGB", canvas_size, background)
            cursor = 0
            for image in opened:
                if direction == "vertical":
                    cross_offset = self._cross_axis_offset(canvas.width, image.width, alignment)
                    position = (cross_offset, cursor)
                    cursor += image.height + gap
                else:
                    cross_offset = self._cross_axis_offset(canvas.height, image.height, alignment)
                    position = (cursor, cross_offset)
                    cursor += image.width + gap
                canvas.paste(image, position)

            safe_name = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", export_name).strip("_") or "stitched"
            target = self._root / f"{safe_name}_{uuid4().hex[:8]}.png"
            canvas.save(target, format="PNG", optimize=True)
            return target
        finally:
            for image in opened:
                image.close()

    @staticmethod
    def _cross_axis_offset(canvas_edge: int, image_edge: int, alignment: str) -> int:
        if alignment == "end":
            return canvas_edge - image_edge
        if alignment == "center":
            return (canvas_edge - image_edge) // 2
        return 0
