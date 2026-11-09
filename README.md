# XRechnung_Slim

Schlanke, eigenständige App, die für Oracle **Suite8** XRechnung-XML erzeugt und
automatisiert an die ausgehenden Folio-Rechnungsmails anhängt.

Sie läuft als Windows-Dienst (NSSM) und pollt die Suite8-DB: für jede zum Versand
markierte Mail (WMAI mit `BLOCKSEND=1`) liest sie die Rechnungsdaten über
vorgefertigte Oracle-Views, baut die XRechnung-XML (EN16931 / XRechnung 3.0),
validiert sie gegen den KoSIT-Validator, hängt sie an die Mail und gibt den
Versand frei. Status und sämtliche Einstellungen über eine Browser-Oberfläche
(Standard `http://127.0.0.1:8022/`) mit Anmeldung.

**Eigenschaften**
- Kein eigener Mailversand — nutzt den Suite8-Mailservice (XML wird nur angehängt).
- **Anmeldung** mit den Rollen „ansehen“ und „verwalten“; alle Einstellungen
  (Datenbank, Hotel, Versand, Rechnungsinhalt, Prüfung, Server, Update) mit
  Erklärtext in der Oberfläche.
- **Gast und Gruppenrechnung:** Gast im Rechnungshinweis (BT-22) und als
  Lieferempfänger (BT-70); bei Gruppenrechnungen Zimmer und Gast je Position,
  gleiche Buchungen zusammengefasst.
- **Nur-XML-Versand** je Kunde (Membership „PDF“) oder für alle: PDF und RTF
  werden aus der Suite8-Mail genommen.
- **Auslagen und Paid-Out** mit 0 % statt Blockade (Artikelliste einstellbar).
- Datums-robuste Rechnungsnummer-Erkennung (mehrsprachige Betreffe, „Nummer eintippen").
- DB-Trigger mit Idempotenz-Guard (kein Doppel-Anhängen).
- Eingebauter **inkrementeller Auto-Updater** (lädt nur geänderte Dateien aus GitHub).
- Nutzt einen 64-bit-Oracle-Client; fehlt er, lädt der Installer den Instant Client.

## Installation (Schnellstart)

Auf dem Suite8-Server als **Administrator** in PowerShell — lädt alle Bausteine
selbst (öffentliches Repo, kein Token nötig):

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/ahornhotels/XRechnung_Slim/master/install_online.ps1 -OutFile $env:TEMP\install_online.ps1; & $env:TEMP\install_online.ps1"
```

Danach `slim\setup_slim.cmd` als Administrator → Wizard auf
`http://127.0.0.1:8022/`. Anschließend **am Server** unter
`http://127.0.0.1:8022/login` den ersten Verwalter anlegen. Voraussetzungen und
der DBA-Trigger-Schritt: siehe **[INSTALL_FROM_GITHUB.md](INSTALL_FROM_GITHUB.md)**,
Bedienung: **[slim/INSTALL.md](slim/INSTALL.md)**.

## Updates

Die Startseite meldet neue Versionen („Update verfügbar“), ein Verwalter klickt
**„Jetzt aktualisieren“**. Der inkrementelle Updater holt aus diesem Repo nur die
seit der laufenden Version geänderten Dateien und startet den Dienst neu.
Konfiguration und Daten bleiben erhalten. Versionspflege:
**[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)**.

> **Update von 1.x auf 2.0:** Danach gibt es noch keinen Benutzer. Einmal am
> Server selbst `http://127.0.0.1:8022/login` öffnen und den ersten Verwalter
> anlegen (von anderen Rechnern aus nicht möglich). Der Rechnungsversand läuft
> bis dahin unverändert weiter.

## Struktur

- `slim/` — die App (FastAPI-API, Poller, Frontend, Setup-Wizard, Install-Skripte)
- `core/` — Basis (Config, Crypto, Oracle-Verbindung, Logging) — vendored
- `modules/` — Pattern-Erkennung, Rechnungsdaten (Fetcher, Adresse/Gast/
  Zusammenfassen), Validator, KoSIT, WMAI-Mailer, XML-Builder
- `sql/` — Abfragen auf die Suite8-Tabellen
- `templates/` — UBL-Vorlagen für Rechnung und Gutschrift
- `validation/` — KoSIT-XRechnung-Validierungsartefakte (Jar git-ignoriert)
- `install/` — Laufzeit-Bundle: portable Python, JRE, NSSM, Oracle Instant
  Client (alles git-ignoriert, wird vom Installer befüllt).
- `vendor/nssm/` — `nssm.exe` (Public Domain), damit der Dienst-Wrapper nicht
  von der Erreichbarkeit von `nssm.cc` abhängt.
- `tests_slim/` — Testsuite
- `install_online.ps1` — Online-Installer (lädt Abhängigkeiten selbst)

## Entwicklung

```sh
python -m pytest tests_slim/      # Tests
python -m slim.main_slim          # App lokal starten (Config in slim/config/)
```

Konfiguration liegt unter `slim/config/` (siehe `*.example`-Dateien), Benutzer
unter `slim/data/users.json`. Echte Hotel-Konfigurationen, Benutzer und Secrets
sind git-ignoriert.

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
  (proprietär, **nicht** redistribuierbar — der Installer lädt ihn direkt von
  `download.oracle.com`, dieses Repo verteilt ihn nicht), Adoptium Temurin JRE (GPLv2+CE),
  portable Python (PSF), pip-Wheels (jeweils eigene, permissive Lizenzen).
