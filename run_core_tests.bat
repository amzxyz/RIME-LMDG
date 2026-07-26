@echo off
cd /d %~dp0
python -m pytest -q tests
pause
