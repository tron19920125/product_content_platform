@echo off
cd /d "%~dp0.."
"%~1" -m uvicorn product_content_platform.api.app:app --host "%~2" --port "%~3" 1>>"%~4" 2>>"%~5"
