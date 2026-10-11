@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0.desktop-deps;%~dp0.venv\Lib\site-packages;%~dp0"
"%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m tools.evaluate_cloud_brain
pause
