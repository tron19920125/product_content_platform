from __future__ import annotations

import io
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from product_content_platform.domain import DomainValidationError


class LocalAssetStore:
    """Stores uploaded bytes below one controlled local root."""

    def __init__(self, root: Path, max_bytes: int = 25 * 1024 * 1024) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._allowed_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}

    def save(self, file_name: str, content: bytes) -> str:
        safe_name = Path(file_name).name.strip()
        if not safe_name or safe_name in {".", ".."}:
            raise DomainValidationError("素材文件名无效")
        suffix = Path(safe_name).suffix.lower()
        if suffix not in self._allowed_suffixes:
            raise DomainValidationError("素材仅支持 PNG、JPG、WEBP 或 PDF")
        if not content:
            raise DomainValidationError("素材文件不能为空")
        if len(content) > self._max_bytes:
            raise DomainValidationError(f"素材超过大小限制: {self._max_bytes} bytes")
        if suffix == ".pdf":
            if not content.startswith(b"%PDF-"):
                raise DomainValidationError("PDF 素材内容无效")
        else:
            try:
                with Image.open(io.BytesIO(content)) as image:
                    image.verify()
                    actual_format = (image.format or "").upper()
            except (UnidentifiedImageError, OSError) as exc:
                raise DomainValidationError("图片素材内容无效") from exc
            expected_formats = {".png": {"PNG"}, ".jpg": {"JPEG"}, ".jpeg": {"JPEG"}, ".webp": {"WEBP"}}
            if actual_format not in expected_formats[suffix]:
                raise DomainValidationError("图片内容与文件扩展名不一致")

        asset_id = str(uuid4())
        target_dir = self._root / asset_id
        target_dir.mkdir(parents=False, exist_ok=False)
        target = target_dir / safe_name
        target.write_bytes(content)
        return str(target.relative_to(self._root))

    def resolve(self, relative_path: str) -> Path:
        target = (self._root / relative_path).resolve()
        if self._root not in target.parents:
            raise DomainValidationError("素材路径超出存储目录")
        return target
