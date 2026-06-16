# XRechnung_Slim

Eigenständige Slim-Variante der Suite8-XRechnung-MiniApp: liest aus der Suite8
Oracle-DB die für eine Rechnung benötigten Daten (über vorgefertigte Views),
erzeugt die XRechnung-XML, hängt sie an die WMAI-Mail an und gibt den Versand
frei. Browser-UI auf `127.0.0.1`, Betrieb als Windows-Dienst via NSSM.

Dieses Repo wurde am 2026-06-15 aus `Suite8XRechnung/slim/` ausgegliedert
(Stand VERSION 1.9.0). Der zuvor geteilte Code (`core/`, `modules/`) ist hier
vendored (eigene Kopie) und entwickelt sich unabhängig von der Big-App weiter.

## Struktur

- `slim/` — die App (FastAPI-API, Poller, Frontend, Setup-Wizard, Install-Skripte)
- `core/` — geteilte Basis (Config, Crypto, Oracle-Verbindung, Logging)
- `modules/` — Pattern-Erkennung, KoSIT-Validator, WMAI-Mailer
- `validation/` — KoSIT-XRechnung-Validierungsartefakte (Jar git-ignoriert)
- `install/` — Deployment-Bundle (Instant Client, JRE, portable Python, NSSM;
  Binärinhalte git-ignoriert)
- `tests_slim/` — Testsuite

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
