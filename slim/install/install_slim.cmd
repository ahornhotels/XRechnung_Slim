@echo off
REM ============================================================
REM Suite8 XRechnung SLIM - NSSM-Installation
REM Voraussetzungen (von der Big-App-Installation mitgebracht):
REM   - install\python\python.exe
REM   - install\nssm.exe
REM   - install\jre\bin\java.exe (KoSIT)
REM   - Aufruf als Administrator
REM ============================================================
SETLOCAL
SET BASE=%~dp0..\..
SET PY=%BASE%\install\python\python.exe
SET NSSM=%BASE%\install\nssm.exe
SET JAVA=%BASE%\install\jre\bin\java.exe
SET SVCNAME=Suite8XRechnungSlim
SET PORT=8022
SET SLIMDIR=%BASE%\slim

echo == Pruefe Voraussetzungen ==
IF NOT EXIST "%PY%"   ( echo FEHLER: Python nicht gefunden in %PY% & EXIT /B 1 )
IF NOT EXIST "%NSSM%" ( echo FEHLER: NSSM nicht gefunden in %NSSM% & EXIT /B 1 )
IF NOT EXIST "%JAVA%" ( echo HINWEIS: Java JRE nicht in %JAVA% - KoSIT wird fehlschlagen )
IF NOT EXIST "%SLIMDIR%\config\hotel.json" (
  echo FEHLER: %SLIMDIR%\config\hotel.json fehlt.
  echo         Aus hotel.json.example anlegen und Hotelwerte eintragen.
  EXIT /B 1
)
IF NOT EXIST "%SLIMDIR%\config\connection.json" (
  echo FEHLER: %SLIMDIR%\config\connection.json fehlt.
  echo         Aus connection.json.example anlegen, dann set_password.py ausfuehren.
  EXIT /B 1
)

echo == Service "%SVCNAME%" (re)installieren ==
"%NSSM%" stop "%SVCNAME%" >NUL 2>&1
"%NSSM%" remove "%SVCNAME%" confirm >NUL 2>&1
"%NSSM%" install "%SVCNAME%" "%PY%" "%SLIMDIR%\main_slim.py"
"%NSSM%" set "%SVCNAME%" AppDirectory "%BASE%"
"%NSSM%" set "%SVCNAME%" DisplayName "Suite8 XRechnung Slim (Suite8-Poller)"
"%NSSM%" set "%SVCNAME%" Description "Standalone Suite8-WMAI-Anhang-Poller (Port %PORT%)"
"%NSSM%" set "%SVCNAME%" Start SERVICE_AUTO_START
"%NSSM%" set "%SVCNAME%" AppStdout "%SLIMDIR%\logs\service-stdout.log"
"%NSSM%" set "%SVCNAME%" AppStderr "%SLIMDIR%\logs\service-stderr.log"
"%NSSM%" set "%SVCNAME%" AppRotateFiles 1
"%NSSM%" set "%SVCNAME%" AppRotateBytes 10485760
"%NSSM%" set "%SVCNAME%" AppEnvironmentExtra "SUITE8_CONFIG_DIR=%SLIMDIR%\config"
"%NSSM%" start "%SVCNAME%"
IF ERRORLEVEL 1 ( echo Service-Start fehlgeschlagen & EXIT /B 1 )

echo.
echo == Installation abgeschlossen ==
echo Service "%SVCNAME%" laeuft auf http://127.0.0.1:%PORT%/
echo Logs: %SLIMDIR%\logs\service-stdout.log
echo.
ENDLOCAL
EXIT /B 0
