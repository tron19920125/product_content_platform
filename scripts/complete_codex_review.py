#!/usr/bin/env python3
"""Persist one evidence-based Studio QA result, or record a retryable failure."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from product_content_platform.studio.creations import Creations
from product_content_platform.studio.quality import Review
from product_content_platform.studio.quality_tasks import QualityChecks
from product_content_platform.studio.settings import StudioSettings
from product_content_platform.studio.workspace import StudioWorkspace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--review", type=Path)
    group.add_argument("--error")
    args = parser.parse_args()
    workspace = StudioWorkspace(StudioSettings.from_environment())
    checks = QualityChecks(workspace, Creations(workspace))
    if args.error:
        result = checks.fail(args.task_id, message=args.error)
    else:
        if not args.review.is_file():
            parser.error("--review must be an existing JSON file")
        result = checks.complete(args.task_id, Review.model_validate(json.loads(args.review.read_text(encoding="utf-8"))))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
