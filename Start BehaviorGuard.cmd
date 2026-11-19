@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0runtime\pythonw.exe" (
  start "" "%~dp0runtime\pythonw.exe" -E -s -B "%~dp0launch.py"
  exit /b 0
)
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" -E -s -B "%~dp0launch.py"
  exit /b 0
)
echo The bundled runtime is missing. Extract the entire BehavioralGuard.zip or run Setup from source.cmd.
pause
exit /b 1
