@echo off
cd /d "%~dp0..\frontend"
"%~1" "%~2" --host "%~3" --port "%~4" --strictPort 1>>"%~5" 2>>"%~6"
