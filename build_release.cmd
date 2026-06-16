@echo off
REM ============================================================
REM XRechnung_Slim - Release-Bundle bauen (Doppelklick-Wrapper)
REM Ruft build_release.ps1 auf. Optional: "-Publish" durchreichen.
REM ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_release.ps1" %*
echo.
pause
