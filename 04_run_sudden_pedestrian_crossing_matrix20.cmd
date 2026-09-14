@echo off
setlocal

cd /d "%~dp0"
set "MANIFEST=C:\Program Files\WindowsNoEditor\VLM-AV\handoffs\20260220_122357\sudden_pedestrian_crossing\manifest.json"

echo ============================================================
echo  CARLA Matrix Runner: Sudden Pedestrian Crossing (20 variants)
echo  Run ID: 20260220_122357
echo ============================================================

python "%~dp0agentic_wine_time_weather_matrix_runner.py" --handoff-manifest "%MANIFEST%"
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE% NEQ 0 (
  echo.
  echo Matrix Stage 2 failed. Check simulation_result_matrix20.json in:
  echo C:\Program Files\WindowsNoEditor\VLM-AV\handoffs\20260220_122357\sudden_pedestrian_crossing
)

exit /b %EXIT_CODE%
