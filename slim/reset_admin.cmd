@echo off
REM ============================================================
REM Suite8 XRechnung Slim - Verwalter-Zugang zuruecksetzen
REM
REM Nur am Server selbst ausfuehren (direkt oder per Remotedesktop).
REM Setzt fuer einen Verwalter ein neues Startpasswort, das bei der
REM naechsten Anmeldung geaendert werden muss. Andere Benutzer bleiben
REM unveraendert. Es gibt dafuer bewusst keine Web-Funktion.
REM ============================================================

SET "SELF=%~dp0"
IF "%SELF:~0,2%"=="\\" (
  echo.
  echo  FEHLER: Dieses Skript darf nur am Server selbst laufen,
  echo          nicht ueber eine Netzwerkfreigabe.
  echo.
  pause
  EXIT /B 5
)

net session >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
  echo.
  echo  Das Zuruecksetzen braucht Administrator-Rechte.
  echo  Gleich erscheint ein UAC-Dialog - bitte auf "JA" klicken.
  echo.
  timeout /T 3 /NOBREAK >nul
  PowerShell -NoProfile -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', '\"%~f0\"' -Verb RunAs"
  EXIT /B 0
)

SETLOCAL
SET "BASE=%~dp0.."
SET "PY=%BASE%\install\python\python.exe"
cd /d "%BASE%"

IF NOT EXIST "%PY%" (
  echo  FEHLER: Python nicht gefunden: %PY%
  pause
  EXIT /B 1
)

echo.
echo  =====================================================================
echo    Suite8 XRechnung Slim - Verwalter-Zugang zuruecksetzen
echo  =====================================================================
echo.
"%PY%" "%BASE%\slim\scripts\reset_admin.py" %*
echo.
pause
ENDLOCAL
