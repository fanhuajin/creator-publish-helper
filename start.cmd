@echo off
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Python environment missing. Please follow README.md to install dependencies.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -u -X utf8 "%~dp0fill_helper.py"
pause
