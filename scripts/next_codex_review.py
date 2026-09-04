#!/usr/bin/env python3
"""Claim one retryable Studio QA task and print its self-contained JSON package."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from product_content_platform.studio.creations import Creations
from product_content_platform.studio.execution import package_review
from product_content_platform.studio.quality_tasks import QualityChecks
from product_content_platform.studio.settings import StudioSettings
from product_content_platform.studio.workspace import StudioWorkspace


def main() -> None:
    workspace = StudioWorkspace(StudioSettings.from_environment())
    creations = Creations(workspace)
    task = QualityChecks(workspace, creations).claim()
    print(json.dumps({"review": package_review(task, workspace) if task else None}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
