@echo off
REM Double-click launcher for the Fundamental Trading Advisor desktop app.
REM Equivalent to running `uv run python -m app desktop` from this folder.
cd /d "%~dp0"
uv run python -m app desktop
pause
