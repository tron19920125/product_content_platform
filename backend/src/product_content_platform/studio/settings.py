from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StudioSettings:
    data_root: Path
    max_references: int = 6
    max_upload_bytes: int = 25 * 1024 * 1024

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_root", self.data_root.expanduser().resolve())
        if not 1 <= self.max_references <= 16:
            raise ValueError("PCP_STUDIO_MAX_REFERENCES 必须在 1–16 之间")
        if self.max_upload_bytes < 1:
            raise ValueError("上传大小限制必须为正整数")

    @classmethod
    def from_environment(cls) -> StudioSettings:
        # Do not inherit PCP_DATA_ROOT or load the old .env: neither old data nor
        # a previously configured Azure deployment should be activated implicitly.
        default_root = Path(__file__).resolve().parents[4] / "data-refactor"
        return cls(
            data_root=Path(os.environ.get("PCP_STUDIO_DATA_ROOT", str(default_root))),
            max_references=int(os.environ.get("PCP_STUDIO_MAX_REFERENCES", "6")),
        )

    def validate_data_root(self) -> None:
        if (self.data_root / "platform.db").exists():
            raise ValueError("新工作区不能使用含 platform.db 的旧数据目录，请设置 PCP_STUDIO_DATA_ROOT")
        for name in ("assets", "production", "exports", "fonts", "cache", "logs", "run", "studio.sqlite3"):
            if (self.data_root / name).is_symlink():
                raise ValueError(f"工作区路径 {name} 不能是符号链接，请使用独立数据目录")

    def initialize(self) -> None:
        self.validate_data_root()
        for name in ("assets", "production", "exports", "fonts", "cache", "logs", "run"):
            (self.data_root / name).mkdir(parents=True, exist_ok=True)

    @property
    def database_path(self) -> Path:
        return self.data_root / "studio.sqlite3"
