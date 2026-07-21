# Projekt-Status / Handoff — XRechnung_Slim

Stand: 2026-07-21 · Version: 1.10.2 · Repo: https://github.com/ahornhotels/XRechnung_Slim (public, GPLv3)

> `v1.10.2` (21.07.2026): Fix — TaxAmount je Steuercode statt Prozentsatz
> korreliert (BR-CO-14-Doppelzählung bei zwei ZTCDs mit gleichem Satz;
> NVL-Fallback gegen stilles 0.00). **SQL nicht gegen V8LIVE gegengeprüft —
> Gegenprüfung mit einer Zwei-Codes-Rechnung nachholen.**
> `v1.10.1` (21.07.2026): Hotfix — `cbc:DueDate` aus dem CreditNote-Template
> entfernt (XSD-Blocker `cvc-complex-type.2.4.a` bei Gutschriften mit
> Fälligkeitsdatum). Bestand seit v1.9.0.
> `v1.10.0` (17.07.2026): Betriebs-Härtungs-Batch — Details unten.

## Kurzfassung

Die Slim-Variante der Suite8-XRechnung-App ist aus `Suite8XRechnung/slim/` in ein
**eigenständiges, öffentliches Repo** ausgegliedert und als **Release `v1.9.0`**
veröffentlicht. Installation läuft über einen **Online-Installer**, Updates über
einen **inkrementellen Auto-Updater**. Big-App bleibt parallel im alten Repo.

## Was erledigt ist

- **Trigger-Idempotenz-Guard:** Der WMAI-BLOCKSEND-Trigger blockt nur noch, wenn
  noch kein XRechnung-XML an der Mail hängt (kein Re-Block/Doppel-Anhängen).
  Oracle-Kompatibilität der Regex-Übersetzung gegen V8LIVE verifiziert.
- **Kombinierter Mehrsprach-Pattern-Editor:** Operator gibt je Sprache
  (deutsch/englisch) Betreff + getippte Rechnungsnummer ein → ein kombiniertes,
  datums-robustes Regex `(?:Anker-DE|Anker-EN)\s*(?P<zinv_number>\d+)`.
- **Eigenständiges Repo:** `core/` und `modules/` sind vendored (eigene Kopie),
  Paketnamen unverändert. Altes Repo um `slim/`+`tests_slim/` bereinigt.
- **Lizenz GPLv3** (`LICENSE`); Drittkomponenten behalten ihre Lizenz.
- **Firmen-Fixtures anonymisiert**; Secrets-Audit sauber (keine Zugangsdaten/
  Schlüssel/PII im getrackten Code).
- **Inkrementeller Auto-Updater:** lädt via GitHub Compare-/Contents-API nur die
  geänderten Dateien (kein ZIP), entfernt gelöschte mit, Fallback auf vollen
  Tree-Abgleich. Ziel-Repo: `ahornhotels/XRechnung_Slim`.
- **Online-Installer** `install_online.ps1`: lädt Code, Python, Temurin JRE, NSSM
  und KoSIT-Validator selbst; nutzt den vorhandenen Oracle-Client des Servers.
- **Dokumentation:** `README.md`, `INSTALL_FROM_GITHUB.md`, `RELEASE_CHECKLIST.md`.

## Neu seit v1.9.0 (Betriebs-Härtung, 2026-07-17)

Design-Spec: `docs/superpowers/specs/2026-07-03-betriebs-haertung-design.md`.

- **BillingReference-Fallback (BG-3):** Gutschrift (381) ohne
  `ZINV_VOID_ZINV_ID` holt die Original-Rechnungsnummer aus dem
  Zahlungs-Kommentar (`ZPOS_COMMENT`, neue Header-Spalte `PaymentRefComment`),
  validiert sie gegen ZINV; kein Treffer → weiterhin Validator-Fehler
  (kein Fake-Bezug). `modules/invoice_fetcher.py`, `sql/invoice_header.sql`.
- **IP-Allowlist für LAN-Zugriff:** `allowed_ips` (IPs/CIDR) in
  `app_settings.json` + `"host": "0.0.0.0"`; localhost immer erlaubt, leere
  Liste = nur localhost. `slim/core_slim/access.py` + Middleware.
- **Zeitstempel auf PC-Zeit:** Audit/Archiv/Status/Updater zeigen lokale
  Serverzeit mit Offset (`…+02:00`) statt UTC. `slim/core_slim/clock.py`.
- **SQL-Fixes vom 03.07. (FW) übernommen** (aus `docs/*_20260703.txt`):
  Kundenadresse-Fallback auf Primäradresse; TaxAmount/InvoiceNet/
  InvoiceTaxTotal aus der Zeilen-Logik (0,5-Cent-Steuerüberschuss bzw.
  Netto+Steuer≠Brutto behoben).
- **Setup-Portkonflikt behoben:** Wizard-Server beendet sich nach „Fertig"
  selbst, `setup_slim.cmd` startet den Dienst danach best-effort neu — der
  vermeintliche „PC-Neustart nach Installation" entfällt.

## Live / Betrieb

- **Installation (Hotel-Server, als Admin):** der PowerShell-Einzeiler aus dem
  README → danach `slim\setup_slim.cmd` → Wizard auf `http://127.0.0.1:8022/`.
- **DB-Trigger:** der Wizard zeigt das Trigger-SQL → **DBA führt es einmalig in
  Oracle (V8LIVE) aus.**
- **Dienst:** `Suite8XRechnungSlim` (NSSM, Autostart, Port 8022).
- **Konfiguration/Daten:** `slim/config/` (Secrets, git-ignoriert), `slim/data/`,
  `slim/logs/`. Bleiben bei Updates unangetastet.
- **Updates:** UI → „Update prüfen / anwenden".

## Tests

- `python -m pytest tests_slim/` → 229 passed, 1 skipped (Live-DB-Integration).

## Offene Punkte / nächste Schritte

- [ ] **SQL-Fixes gegen V8LIVE gegenprüfen:** eine Rechnung, die vorher den
      0,5-Cent-Fehler warf, durch den Poller/„run-now" schicken.
- [ ] **Erster echter End-to-End-Test** des Online-Installers auf einer frischen
      Test-Maschine/VM (in dieser Umgebung nicht möglich — Repo musste erst live
      sein). Verifiziert wurden bisher: Syntax, alle Download-URLs, Logik.
- [ ] **Erstmigration der Alt-Hotels:** Instanzen, die noch die alte Slim aus
      `Suite8XRechnung` (ZIP-Updater) laufen haben, kommen **nicht** automatisch
      auf dieses Repo — einmalig manuell per Online-Installer neu aufsetzen;
      danach greift der inkrementelle Updater.
- [ ] Optional: GPLv3-Kurz-Header in den Quelldateien ergänzen (derzeit nur
      `LICENSE` + README-Sektion).

## Wichtige Dateien

- `install_online.ps1` — Online-Bootstrap-Installer
- `slim/setup_slim.cmd` — Setup-Wizard-Starter (als Admin)
- `slim/core_slim/updater.py` — inkrementeller Updater (Ziel-Repo + Logik)
- `slim/api_slim/trigger_sql.py` — Trigger-SQL inkl. Idempotenz-Guard
- `modules/suite8_pattern.py` — Pattern-Erzeugung/-Erkennung
- `INSTALL_FROM_GITHUB.md` / `RELEASE_CHECKLIST.md` — Install- / Release-Anleitung

## Git-Stand

- Branch `master`, aktuelles Release/Tag `v1.10.2` (21.07.2026, TaxAmount-
  ZTCD-Korrelation); Vorgänger `v1.10.1` (CreditNote-DueDate-Hotfix),
  `v1.10.0` (Betriebs-Härtung), `v1.9.0` @ `1b419bf`.
