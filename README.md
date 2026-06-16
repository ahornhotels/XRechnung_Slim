# XRechnung_Slim

Schlanke, eigenständige App, die für Oracle **Suite8** XRechnung-XML erzeugt und
automatisiert an die ausgehenden Folio-Rechnungsmails anhängt.

Sie läuft als Windows-Dienst (NSSM) und pollt die Suite8-DB: für jede zum Versand
markierte Mail (WMAI mit `BLOCKSEND=1`) liest sie die Rechnungsdaten über
vorgefertigte Oracle-Views, baut die XRechnung-XML (EN16931 / XRechnung 3.0),
validiert sie gegen den KoSIT-Validator, hängt sie an die Mail und gibt den
Versand frei. Konfiguration und Status über eine Browser-Oberfläche auf
`127.0.0.1`.

**Eigenschaften**
- Kein eigener Mailversand — nutzt den Suite8-Mailservice (XML wird nur angehängt).
- Datums-robuste Rechnungsnummer-Erkennung (mehrsprachige Betreffe, „Nummer eintippen").
- DB-Trigger mit Idempotenz-Guard (kein Doppel-Anhängen).
- Eingebauter **inkrementeller Auto-Updater** (lädt nur geänderte Dateien aus GitHub).
- Nutzt den auf dem Suite8-Server vorhandenen Oracle-Client.

## Installation (Schnellstart)

Auf dem Suite8-Server als **Administrator** in PowerShell — lädt alle Bausteine
selbst (öffentliches Repo, kein Token nötig):

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/ahornhotels/XRechnung_Slim/master/install_online.ps1 -OutFile $env:TEMP\install_online.ps1; & $env:TEMP\install_online.ps1"
```

Danach `slim\setup_slim.cmd` als Administrator → Wizard auf
`http://127.0.0.1:8022/`. Voraussetzungen und der DBA-Trigger-Schritt:
siehe **[INSTALL_FROM_GITHUB.md](INSTALL_FROM_GITHUB.md)**.

## Updates

Im UI **„Update prüfen / anwenden"** — der inkrementelle Updater holt aus diesem
Repo nur die seit der laufenden Version geänderten Dateien und startet den Dienst
neu. Konfiguration und Daten bleiben erhalten. Versionspflege:
**[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)**.

## Struktur

- `slim/` — die App (FastAPI-API, Poller, Frontend, Setup-Wizard, Install-Skripte)
- `core/` — Basis (Config, Crypto, Oracle-Verbindung, Logging) — vendored
- `modules/` — Pattern-Erkennung, KoSIT-Validator, WMAI-Mailer, XML-Builder
- `validation/` — KoSIT-XRechnung-Validierungsartefakte (Jar git-ignoriert)
- `install/` — Laufzeit-Bundle: portable Python, JRE, NSSM (git-ignoriert).
  Der Oracle-Client wird vom Suite8-Server genutzt, nicht mitgeliefert.
- `tests_slim/` — Testsuite
- `install_online.ps1` — Online-Installer (lädt Abhängigkeiten selbst)

## Entwicklung

```sh
python -m pytest tests_slim/      # Tests
python -m slim.main_slim          # App lokal starten (Config in slim/config/)
```

Konfiguration liegt unter `slim/config/` (siehe `*.example`-Dateien).
Echte Hotel-Konfigurationen und Secrets sind git-ignoriert.

## Lizenz

Copyright (C) 2026 Ahorn Hotels

Dieses Programm ist freie Software: Sie können es unter den Bedingungen der
**GNU General Public License v3.0** (oder einer späteren Version) weitergeben
und/oder modifizieren — siehe [`LICENSE`](LICENSE). Es wird ohne jegliche
Gewährleistung bereitgestellt.

**Drittkomponenten** behalten ihre jeweils eigene Lizenz:
- `validation/xrechnung-3.0.2/` — KoSIT/EN16931-Validierungsartefakte, Apache-2.0
  (siehe die dortigen `README.md`/`CHANGELOG.md`).
- Laufzeit-Bundle (git-ignoriert, nicht Teil des Repos): Oracle Instant Client
  (proprietär, **nicht** redistribuierbar), Adoptium Temurin JRE (GPLv2+CE),
  portable Python (PSF), pip-Wheels (jeweils eigene, permissive Lizenzen).
