from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from uuid import uuid4


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
