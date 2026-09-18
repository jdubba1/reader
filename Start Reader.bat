@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 scripts\companion.py
) else (
  python scripts\companion.py
)
pause
