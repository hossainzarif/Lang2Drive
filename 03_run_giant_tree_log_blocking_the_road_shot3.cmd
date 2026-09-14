@echo off
setlocal

cd /d "%~dp0"
set "MANIFEST=C:\Program Files\WindowsNoEditor\VLM-AV\handoffs\20260222_141049_896767\giant_tree_log_blocking_the_road\manifest.json"

echo ============================================================
echo  CARLA Scene Runner: Giant Tree Log Blocking the Road -- Shot 3 [V3]
echo  Run ID: 20260222_141049_896767
echo  Compliance: mesh-staticmeshfactory-sync
echo ============================================================

python "%~dp0agentic_wine_handoff_runner.py" --handoff-manifest "%MANIFEST%"
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE% NEQ 0 (
  echo.
  echo Stage 2 simulation failed. Check logs in:
  echo C:\Program Files\WindowsNoEditor\VLM-AV\handoffs\20260222_141049_896767\giant_tree_log_blocking_the_road
)

exit /b %EXIT_CODE%
