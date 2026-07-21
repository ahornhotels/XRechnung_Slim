@echo off
REM ============================================================
REM Suite8 XRechnung Slim - Setup-Doppelklick-Starter
REM
REM Robust gegen:
REM   - Doppelklick ohne Admin-Rechte (UAC-Elevation via PowerShell
REM     mit cmd /k, das Fenster bleibt offen auch bei Fehler)
REM   - Fehlende Python/Slim-Files (klare Fehlermeldung + pause)
REM   - Uvicorn-Crash (pause statt sofortiges Schliessen)
REM
REM Falls dieses Skript IMMER NOCH zu schnell schliesst:
REM   Rechtsklick auf setup_slim.cmd -> "Als Administrator ausfuehren"
REM ============================================================

REM ─── 1) Admin-Check ───────────────────────────────────────
net session >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
  cls
  echo.
  echo   ##########################################################
  echo   #                                                        #
  echo   #     Suite8 XRechnung Slim - Setup-Assistent            #
  echo   #                                                        #
  echo   ##########################################################
  echo.
  echo   Das Setup braucht Administrator-Rechte fuer die
  echo   Service-Installation.
  echo.
  echo   GLEICH ERSCHEINT EIN UAC-DIALOG:
  echo     "Moechten Sie zulassen, dass durch diese App
  echo      Aenderungen an Ihrem Geraet vorgenommen werden?"
  echo.
  echo   Bitte auf "JA" klicken.
  echo.
  echo   Es oeffnet sich dann ein NEUES schwarzes Fenster mit
  echo   dem Setup-Assistenten - bitte BEIDE Fenster offen lassen.
  echo.
  echo   ----------------------------------------------------------
  echo   Falls Sie den UAC-Dialog uebersehen oder ablehnen:
  echo   Rechtsklick auf setup_slim.cmd
  echo   -^> "Als Administrator ausfuehren"
  echo   ----------------------------------------------------------
  echo.
  echo   Warten Sie 5 Sekunden, dann erscheint der UAC-Dialog...
  echo.
  timeout /T 5 /NOBREAK >nul

  REM cmd /k laesst das neu geoeffnete Admin-Fenster OFFEN, auch
  REM wenn das eigentliche Setup-Skript spaeter mit Fehler aussteigt.
  REM Ohne /k wuerde der User die Fehlermeldung nicht lesen koennen.
  PowerShell -NoProfile -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', '\"%~f0\"' -Verb RunAs"

  echo.
  echo   Dieses Fenster kann jetzt geschlossen werden.
  echo   Der Setup-Assistent laeuft im neuen Fenster weiter.
  echo.
  pause
  EXIT /B 0
)

REM ─── 2) Wir sind Admin — eigentliches Setup ──────────────
cls
echo.
echo  =====================================================================
echo    Suite8 XRechnung Slim - Setup-Assistent (Administrator-Modus)
echo  =====================================================================
echo.

SETLOCAL ENABLEDELAYEDEXPANSION
SET BASE=%~dp0..
SET PY=%BASE%\install\python\python.exe
SET SLIMDIR=%BASE%\slim

cd /d "%BASE%"

echo  [1/5] Voraussetzungen pruefen...

IF NOT EXIST "%PY%" (
  echo.
  echo  ╔══════════════════════════════════════════════════════════════╗
  echo  ║  FEHLER: Python nicht gefunden                               ║
  echo  ╚══════════════════════════════════════════════════════════════╝
  echo.
  echo  Erwartet:   %PY%
  echo.
  echo  Loesung:    Den Online-Installer install_online.ps1 erneut
  echo              ausfuehren - er laedt den eingebetteten Python nach
  echo              install\python.
  echo.
  echo  Druecken Sie eine Taste um dieses Fenster zu schliessen.
  pause
  EXIT /B 1
)
echo        Python   OK: %PY%

IF NOT EXIST "%SLIMDIR%\main_slim.py" (
  echo.
  echo  ╔══════════════════════════════════════════════════════════════╗
  echo  ║  FEHLER: Slim-Quellcode fehlt                                ║
  echo  ╚══════════════════════════════════════════════════════════════╝
  echo.
  echo  Erwartet:   %SLIMDIR%\main_slim.py
  echo.
  echo  Loesung:    git pull im Repository ausfuehren.
  echo.
  pause
  EXIT /B 1
)
echo        Slim     OK: %SLIMDIR%

echo.
echo  [2/5] Verzeichnisse vorbereiten...
IF NOT EXIST "%SLIMDIR%\data"   mkdir "%SLIMDIR%\data"   >NUL 2>&1
IF NOT EXIST "%SLIMDIR%\logs"   mkdir "%SLIMDIR%\logs"   >NUL 2>&1
IF NOT EXIST "%SLIMDIR%\config" mkdir "%SLIMDIR%\config" >NUL 2>&1
echo        slim\data, slim\logs, slim\config ok

echo.
echo  [3/5] Konfigurations-Templates anlegen ^(falls noch nicht da^)...
IF NOT EXIST "%SLIMDIR%\config\hotel.json" (
  copy /Y "%SLIMDIR%\config\hotel.json.example" "%SLIMDIR%\config\hotel.json" >NUL
  echo        hotel.json aus Template angelegt
) ELSE (
  echo        hotel.json existiert bereits ^(unangetastet^)
)
IF NOT EXIST "%SLIMDIR%\config\app_settings.json" (
  copy /Y "%SLIMDIR%\config\app_settings.json.example" "%SLIMDIR%\config\app_settings.json" >NUL
  echo        app_settings.json aus Template angelegt
) ELSE (
  echo        app_settings.json existiert bereits ^(unangetastet^)
)
REM connection.json wird absichtlich NICHT vorab angelegt -
REM der Wizard speichert sie erst nach erfolgreichem Verbindungstest.

SET SUITE8_CONFIG_DIR=%SLIMDIR%\config
REM Kontext-Flag: nur DIESER (Wizard-)Prozess darf sich nach /finish selbst
REM beenden. Der NSSM-Dienst setzt das Flag nicht und ueberlebt ein Re-Setup.
SET SUITE8_SETUP_WIZARD=1

echo.
echo  [4/5] Browser-Start vorbereiten...
REM Browser wird mit 4-Sekunden-Verzoegerung gestartet, damit der
REM uvicorn-Server Zeit hat hochzufahren bevor /setup geladen wird.
start /B "" cmd /c "ping 127.0.0.1 -n 5 >nul & start http://127.0.0.1:8022/"
echo        Browser wird in ca. 4 Sekunden geoeffnet.

echo.
echo  [5/5] Wizard-Server wird gestartet...
echo.
echo  =====================================================================
echo.
echo   Browser oeffnet sich automatisch auf http://127.0.0.1:8022/
echo.
echo   Falls nicht: URL manuell in den Browser eingeben.
echo.
echo   Dieses Fenster BLEIBT OFFEN waehrend Sie den Wizard durchklicken.
echo   Wenn der Wizard "Fertig" anzeigt und der Service installiert ist:
echo   einfach dieses Fenster schliessen oder Strg-C druecken.
echo.
echo   Service-Logs danach unter: %SLIMDIR%\logs\service-stdout.log
echo.
echo  =====================================================================
echo.

"%PY%" -m uvicorn slim.main_slim:app --host 127.0.0.1 --port 8022 --log-level info

REM ─── 3) Wizard-Server ist beendet ────────────────────────
REM Nur wenn der Wizard in DIESEM Lauf ein Setup abgeschlossen hat, hinterlaesst
REM /api/setup/finish die Signal-Datei .restart_after_setup. Dann den frisch
REM installierten Dienst anstossen (Port-Uebergabe). Bei Abbruch, Bind-Fehler
REM oder Wizard-Aufruf auf einer bereits fertigen Installation existiert die
REM Datei nicht -> der laufende/gestoppte Dienst wird NICHT ungewollt gebounct.
IF EXIST "%SLIMDIR%\config\.restart_after_setup" (
  DEL "%SLIMDIR%\config\.restart_after_setup" >NUL 2>&1
  IF EXIST "%BASE%\install\nssm.exe" (
    "%BASE%\install\nssm.exe" restart Suite8XRechnungSlim >NUL 2>&1
  )
)

echo.
echo  =====================================================================
echo   Wizard-Server wurde beendet.
echo  =====================================================================
echo.
echo   Falls Sie den Wizard noch nicht durchgeklickt haben:
echo   Bitte dieses Skript erneut starten ^(setup_slim.cmd^).
echo.
echo   Falls Sie ihn schon durchgeklickt haben:
echo   Der Service "Suite8XRechnungSlim" laeuft jetzt selbstaendig.
echo   URL:   http://127.0.0.1:8022/
echo   Logs:  %SLIMDIR%\logs\service-stdout.log
echo.
pause
ENDLOCAL
