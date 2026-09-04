#!/usr/bin/env python3
"""Persist one Codex image plus its evidence-based QA report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from product_content_platform.studio.creations import Creations
from product_content_platform.studio.quality import Review
from product_content_platform.studio.settings import StudioSettings
from product_content_platform.studio.workspace import StudioWorkspace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("image", type=Path)
    parser.add_argument("review", type=Path)
    args = parser.parse_args()
    if not args.image.is_file() or args.image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        parser.error("image must be an existing PNG/JPG/WebP file")
    if not args.review.is_file():
        parser.error("review must be an existing JSON file")
    workspace = StudioWorkspace(StudioSettings.from_environment())
    review = Review.model_validate(json.loads(args.review.read_text(encoding="utf-8")))
    asset = workspace.upload_image(args.image.name, "style", args.image.read_bytes())
    version = Creations(workspace).complete(
        args.job_id, asset_id=asset["id"], review=review,
        provenance={"provider": "codex-built-in", "note": "由 Codex 生图并完成证据化检查；实际像素由素材记录保存。"},
    )
    print(json.dumps(version, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
