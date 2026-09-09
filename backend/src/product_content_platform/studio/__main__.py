"""Isolated Studio entry point with explicit opt-in Azure credential loading."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path
from copy import deepcopy

import uvicorn

from .api import create_app
from .settings import StudioSettings


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the isolated studio input backend (not the old UI).")
    parser.add_argument("--check", action="store_true", help="Validate configuration without creating files or starting a server")
    parser.add_argument("--port", type=int, default=os.environ.get("PCP_STUDIO_PORT", "8010"))
    parser.add_argument("--azure-env", type=Path, help="Explicitly load Azure credentials from this file and start the automatic executor")
    arguments = parser.parse_args()
    if not 1 <= arguments.port <= 65535:
        parser.error("port must be between 1 and 65535")
    settings = StudioSettings.from_environment()
    if arguments.azure_env:
        from .azure import load_azure_environment
        load_azure_environment(arguments.azure_env)
        settings = replace(settings, generation_provider="azure")
    settings.validate_data_root()
    print(json.dumps({
        "workspace": "studio", "data_root": str(settings.data_root),
        "url": f"http://127.0.0.1:{arguments.port}/docs",
        "stage": "local-studio-beta", "generation_available": False,
        "generation_submission_available": True, "demo_available": True,
        "legacy_environment_loaded": False,
        "azure_environment_loaded": bool(arguments.azure_env),
        "generation_provider": settings.generation_provider,
    }, ensure_ascii=False), flush=True)
    if arguments.check:
        return

    settings.initialize()
    logging_config = deepcopy(uvicorn.config.LOGGING_CONFIG)
    logging_config["handlers"]["studio_file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(settings.data_root / "logs" / "backend.log"),
        "maxBytes": 2_000_000, "backupCount": 2, "encoding": "utf-8", "formatter": "default",
    }
    logging_config["loggers"]["uvicorn"]["handlers"].append("studio_file")
    # Access logging is disabled: arbitrary input/filenames may be in query strings.
    # Foreground execution needs no PID file and stops with Ctrl+C.
    uvicorn.run(create_app(settings), host="127.0.0.1", port=arguments.port, log_config=logging_config, access_log=False)


if __name__ == "__main__":
    main()
