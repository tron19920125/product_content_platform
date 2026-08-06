from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    data_root: Path
    database_path: Path
    asset_root: Path
    production_root: Path
    export_root: Path
    generation_mode: str
    qa_mode: str

    @classmethod
    def from_environment(cls) -> Settings:
        default_root = Path(__file__).resolve().parents[3] / "data"
        data_root = Path(os.environ.get("PCP_DATA_ROOT", default_root)).expanduser().resolve()
        generation_mode = os.environ.get("PCP_GENERATION_MODE", "local").strip().lower()
        qa_mode = os.environ.get("PCP_QA_MODE", "local").strip().lower()
        if generation_mode not in {"local", "azure"}:
            raise ValueError("PCP_GENERATION_MODE 必须是 local 或 azure")
        if qa_mode not in {"local", "azure"}:
            raise ValueError("PCP_QA_MODE 必须是 local 或 azure")
        return cls(
            data_root=data_root,
            database_path=data_root / "platform.db",
            asset_root=data_root / "assets",
            production_root=data_root / "production",
            export_root=data_root / "exports",
            generation_mode=generation_mode,
            qa_mode=qa_mode,
        )
