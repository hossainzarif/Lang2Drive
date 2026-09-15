@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: 04_run_scene_matrix8.cmd "path\to\manifest.json"
  exit /b 2
)
python "%~dp0agentic_wine_time_weather_matrix_runner.py" --handoff-manifest "%~1"
exit /b %ERRORLEVEL%
