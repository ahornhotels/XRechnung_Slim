# Projekt-Status / Handoff — XRechnung_Slim

Stand: 2026-07-23 · Version: 1.10.4 · Repo: https://github.com/ahornhotels/XRechnung_Slim (public, GPLv3)

## Kurzfassung

Die Slim-Variante der Suite8-XRechnung-App ist ein **eigenständiges, öffentliches
Repo**. Installation über einen **Online-Installer**, Updates über einen
**inkrementellen Auto-Updater** (GitHub Compare-/Contents-API, nur geänderte
Dateien). Big-App bleibt parallel im alten Repo `Suite8XRechnung`.

Seit v1.9.0 (16.06.2026) kamen v1.10.0 (Betriebs-Härtung) und die Hotfix-/Fix-Serie
v1.10.1–v1.10.4 dazu. **Aktuell keine offene Code-Baustelle** — der Arbeitsbaum ist
sauber, alle Releases sind getaggt und gepusht. Offen sind nur **Betriebs-
Gegenprüfungen** (siehe unten) und ein zurückgestellter Cleanup.

## Release-Historie (diese Serie)

| Tag | Datum | Inhalt |
|-----|-------|--------|
| `v1.9.0`  | 16.06. | Ausgliederung ins eigene Repo, Online-Installer, Auto-Updater |
| `v1.10.0` | 17.07. | Betriebs-Härtung: BG-3-Fallback, IP-Allowlist, PC-Zeit, SQL-Fixes (FW 03.07.), Setup-Portkonflikt |
| `v1.10.1` | 21.07. | Hotfix: `cbc:DueDate` aus CreditNote-Template (XSD-Blocker `cvc-complex-type.2.4.a` bei Gutschriften) — bestand seit v1.9.0 |
| `v1.10.2` | 21.07. | **Fix TaxAmount je Steuercode** statt Prozentsatz (BR-CO-14-Doppelzählung bei 2 ZTCDs gleichen Satzes; NVL-Fallback gegen stilles 0.00) |
| `v1.10.3` | 21.07. | Review-Nachlauf Findings #7–#17 (siehe unten) |
| `v1.10.4` | 21.07. | **Fix Adress-Fallback** deterministisch aus min(xadr_id) statt rownum=1 (Finding 8) |

## Code-Review-Kontext (diese Sitzung)

Ein **Max-Effort-Multi-Agent-Review** (`/code-review max`) über den v1.10.0-Batch
fand 12 verifizierte Findings. Alle 12 sind adressiert:

- **Finding 1** (kritisch, BR-CO-14 TaxAmount) → v1.10.2
- **CreditNote-DueDate** (im Deployment aufgefallen, nicht aus dem Review) → v1.10.1
- **Findings 2,3,4,5,6,7,9,10,12** → v1.10.3 (BG-3-Selbstreferenz/Dublette/Override-IssueDate,
  Wizard-Self-Shutdown nur bei Erfolg, setup_finish-Kontext-Guard, LAN-Warnung + /healthz frei,
  Allowlist-IPv6-Normalisierung, veraltete-Override-Warnung, Archiv-Epoch-Sortierung)
- **Finding 8** (Adress-Fallback) → v1.10.4
- **Finding 11** (SQL dreifach kopiert) → **nur Divergenz-Guard** in v1.10.3;
  eigentliche Konsolidierung **zurückgestellt** (Umbau der Steuerlogik, nur mit DB-Test sinnvoll).

3 Verdachtsfälle wurden im Verify-Pass widerlegt (Totals-NULL bei History-Rechnungen,
NULL-Steuersatz-Zeilen, Unicode-Ziffern-Crash) — der Validator fängt diese vorher ab.

## Offene Punkte / nächste Schritte

**Betriebs-Gegenprüfungen (kein Code, an echter Umgebung/V8LIVE):**

- [ ] **v1.10.2 gegen V8LIVE prüfen** — Rechnung mit **zwei gleichprozentigen
      Steuercodes** (z.B. 19% Logis + 19% F&B): Summe der TaxSubtotal-Beträge muss
      = TaxAmountTot sein (vorher doppelt). Plus normale Ein-Satz-Rechnung als
      Regressionscheck. Prüf-SQL: `docs/V8LIVE_gegenpruefung.md`.
- [ ] **v1.10.4 gegen V8LIVE prüfen** — Trigger-Check: gibt es Gäste mit >1
      Primäradresse? (0 Zeilen → Fix ist folgenlose Absicherung.) Prüf-SQL:
      `docs/V8LIVE_gegenpruefung.md`.
- [ ] **v1.10.3 Setup-Ablauf an echter Instanz durchklicken** — nach „Fertig"
      soll der Wizard sich beenden, `nssm restart` den Dienst anstoßen und das
      Frontend per /healthz-Poll sauber auf die Status-Seite umschalten. Nur an
      einer realen Installation prüfbar (Python-Logik ist unit-getestet).

> **Wichtig:** Die SQL-Fixes v1.10.2 und v1.10.4 gingen **ohne V8LIVE-Gegenprüfung**
> live (bewusste Entscheidung des Betreibers). Marker-Guard-Tests sichern die
> Struktur, nicht die Oracle-Laufzeit.

**Code (offen):**

- [ ] **Finding 11 — SQL-Konsolidierung:** Die Zeilen-Berechnungslogik ist dreifach
      kopiert (`sql/invoice_lines.sql` + CTEs in `invoice_tax.sql`/`invoice_totals.sql`).
      Divergenz-Guard (`tests_slim/test_sql_templates.py::test_zeilenlogik_synchron_ueber_drei_sql`)
      fängt stille Abweichung ab. Echte Konsolidierung (z.B. Netto/Steuer in Python aus
      den bereits gefetchten `lines` summieren) ist ein Umbau der Steuerlogik →
      nur mit V8LIVE-Test angehen. Caveats: History-Zweige (ZPI2/ZPO2) → bei leeren
      lines None statt 0; TaxAmount braucht Gruppierung je Steuersatz.

**Altbestand (aus v1.9.0-Handoff, weiter offen):**

- [ ] Erster echter **End-to-End-Test des Online-Installers** auf frischer VM.
- [ ] **Erstmigration der Alt-Hotels** (alte Slim aus `Suite8XRechnung`, ZIP-Updater):
      einmalig manuell per Online-Installer neu aufsetzen, danach greift der
      inkrementelle Updater.
- [ ] Optional: GPLv3-Kurz-Header in Quelldateien (derzeit nur `LICENSE` + README).

## Live / Betrieb

- **Installation (Hotel-Server, als Admin):** PowerShell-Einzeiler aus dem README →
  `slim\setup_slim.cmd` → Wizard auf `http://127.0.0.1:8022/`.
- **DB-Trigger:** der Wizard zeigt das Trigger-SQL → **DBA führt es einmalig in
  Oracle (V8LIVE) aus.**
- **Dienst:** `Suite8XRechnungSlim` (NSSM, Autostart, Port 8022).
- **LAN-Zugriff:** `"host": "0.0.0.0"` + `"allowed_ips"` (IPs/CIDR) in
  `slim/config/app_settings.json`; localhost immer erlaubt, leere Liste = nur
  localhost (Startup-Warnung im Log). `/healthz` ist immer frei (Monitoring).
- **Konfiguration/Daten:** `slim/config/` (Secrets, git-ignoriert), `slim/data/`,
  `slim/logs/`. Bleiben bei Updates unangetastet.
- **Updates:** UI → „Update prüfen / anwenden".

## Tests

- `python -m pytest tests_slim/` → **247 passed, 1 skipped** (Live-DB-Integration).

## Wichtige Dateien

- `install_online.ps1` — Online-Bootstrap-Installer
- `slim/setup_slim.cmd` — Setup-Wizard-Starter (setzt `SUITE8_SETUP_WIZARD=1`)
- `slim/api_slim/setup_api.py` — Wizard-Endpoints, Self-Shutdown-Logik
- `slim/core_slim/updater.py` — inkrementeller Updater (Ziel-Repo + Logik)
- `slim/core_slim/access.py` — IP-Allowlist-Middleware
- `modules/invoice_fetcher.py` — Rohdaten-Fetch, BG-3-Fallback, `_read_sql`-Overrides
- `modules/xml_builder.py` — Rendering, `_ensure_duedate`, CreditNote-Behandlung
- `sql/invoice_header.sql` · `invoice_tax.sql` · `invoice_totals.sql` — Steuer-/Adress-SQL
- `docs/V8LIVE_gegenpruefung.md` — read-only Prüf-Queries für die offenen SQL-Fixes
- `docs/superpowers/specs/2026-07-03-betriebs-haertung-design.md` — Design-Spec v1.10.0
- `INSTALL_FROM_GITHUB.md` / `RELEASE_CHECKLIST.md` — Install- / Release-Anleitung

## Release-How-To (kurz, aus dieser Serie bewährt)

1. `VERSION` bumpen, STATUS.md nachziehen, committen.
2. `git tag -a vX.Y.Z -m "..."`, `git push origin master`, `git push origin vX.Y.Z`.
3. GitHub-Release: `gh` ist auf diesem Host **nicht** installiert → per REST-API mit
   dem Token aus `git credential fill` (Muster siehe Git-Historie der Release-Commits).
4. Verifizieren: `releases/latest` meldet den neuen Tag (was der Auto-Updater abfragt).

## Git-Stand

- Branch `master`, aktuelles Release/Tag `v1.10.4` (21.07.2026, Adress-Fallback-
  Determinismus). Arbeitsbaum sauber, alles gepusht.
- Tag-Kette: `v1.10.4` → `v1.10.3` → `v1.10.2` → `v1.10.1` → `v1.10.0` → `v1.9.0` @ `1b419bf`.
