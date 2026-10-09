@echo off
set "CREATOR_UV=%USERPROFILE%\.local\bin\uv.exe"
if not exist "%CREATOR_UV%" set "CREATOR_UV=%~dp0.venv\Scripts\uv.exe"
if not exist "%CREATOR_UV%" set "CREATOR_UV=uv"
"%CREATOR_UV%" run --no-project --python 3.13 --with windows-mcp==0.8.5 python -B -u -X utf8 "%~dp0multi_publish.py"
pause
