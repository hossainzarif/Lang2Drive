@echo off
setlocal

cd /d "%~dp0"

set "MANIFEST=C:\Program Files\WindowsNoEditor\VLM-AV\handoffs\20260220_123052_486705\oil_spill_hazard\manifest.json"
set "MAX_ATTEMPTS=3"
set "ATTEMPT=1"

:retry
echo [OIL SPILL shot_5] attempt %ATTEMPT%/%MAX_ATTEMPTS%
python "%~dp0agentic_wine_handoff_runner.py" --timeout 480 --handoff-manifest "%MANIFEST%"
if %ERRORLEVEL% EQU 0 goto :ok

if %ATTEMPT% GEQ %MAX_ATTEMPTS% goto :failed
set /a ATTEMPT+=1
echo [OIL SPILL] run failed, retrying after short cooldown...
ping -n 9 127.0.0.1 >nul 2>&1
goto :retry

:ok
echo.
echo Oil Spill shot_5 simulation completed successfully.
exit /b 0

:failed
echo.
echo Oil Spill shot_5 simulation failed after %MAX_ATTEMPTS% attempts.
echo Check: C:\Program Files\WindowsNoEditor\VLM-AV\handoffs\20260220_123052_486705\oil_spill_hazard
exit /b 1
