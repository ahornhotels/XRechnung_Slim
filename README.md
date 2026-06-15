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
