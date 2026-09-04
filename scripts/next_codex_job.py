#!/usr/bin/env python3
"""Claim one queued Studio job and print a self-contained JSON task for Codex."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from product_content_platform.studio.creations import Creations
from product_content_platform.studio.execution import package_job
from product_content_platform.studio.settings import StudioSettings
from product_content_platform.studio.workspace import StudioWorkspace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation")
    args = parser.parse_args()
    workspace = StudioWorkspace(StudioSettings.from_environment())
    job = Creations(workspace).claim(args.operation)
    print(json.dumps({"job": package_job(job, workspace) if job else None}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
