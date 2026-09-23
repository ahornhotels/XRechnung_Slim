# Projekt-Status / Handoff — XRechnung_Slim

Stand: 2026-09-23 · Version: 1.10.6 · Repo: https://github.com/ahornhotels/XRechnung_Slim (public, GPLv3)

## Kurzfassung

Die Slim-Variante der Suite8-XRechnung-App ist ein **eigenständiges, öffentliches
Repo**. Installation über einen **Online-Installer**, Updates über einen
**inkrementellen Auto-Updater** (GitHub Compare-/Contents-API, nur geänderte
Dateien). Big-App bleibt parallel im alten Repo `Suite8XRechnung`.

Seit v1.9.0 (16.06.2026) kamen v1.10.0 (Betriebs-Härtung), die Hotfix-/Fix-Serie
v1.10.1–v1.10.4, v1.10.5 (Fehler-XML-Diagnose) und v1.10.6 (BG-23-Abgleich)
dazu. Die v1.10.5-Diagnose half direkt, einen Feld-Vorfall zu lösen (BG-3 bei
Gutschrift durch veralteten SQL-Override, siehe unten); v1.10.6 behebt einen
zweiten (BR-Z-01 bei 0-%-Buchungen, siehe unten). **Keine größere Code-Baustelle** — der Arbeitsbaum ist
sauber, alle Releases sind getaggt und gepusht; offen nur ein kosmetischer
Template-Fix, **Betriebs-Gegenprüfungen** (siehe unten) und ein zurückgestellter
Cleanup.

Neu (08.09.2026, keine Code-Änderung): ein **bedienerfreundliches
Einbindungshandbuch** für IT/DBA/Front Office (nicht-technisch, mit konkreten
Suite8-Klickpfaden statt DB-Feldnamen) unter `docs/handbuch/` — als HTML zum
lokalen Öffnen im Browser und als ODT zum Bearbeiten in Word/LibreOffice, siehe
„Einbindungshandbuch" unten. Dabei wurde außerdem die Gutschrift/Storno-Logik
von Slim gegen Suite8-Doku und Code verifiziert (siehe „Gutschriften/Stornorechnungen").

## Release-Historie (diese Serie)

| Tag | Datum | Inhalt |
|-----|-------|--------|
| `v1.9.0`  | 16.06. | Ausgliederung ins eigene Repo, Online-Installer, Auto-Updater |
| `v1.10.0` | 17.07. | Betriebs-Härtung: BG-3-Fallback, IP-Allowlist, PC-Zeit, SQL-Fixes (FW 03.07.), Setup-Portkonflikt |
| `v1.10.1` | 21.07. | Hotfix: `cbc:DueDate` aus CreditNote-Template (XSD-Blocker `cvc-complex-type.2.4.a` bei Gutschriften) — bestand seit v1.9.0 |
| `v1.10.2` | 21.07. | **Fix TaxAmount je Steuercode** statt Prozentsatz (BR-CO-14-Doppelzählung bei 2 ZTCDs gleichen Satzes; NVL-Fallback gegen stilles 0.00) |
| `v1.10.3` | 21.07. | Review-Nachlauf Findings #7–#17 (siehe unten) |
| `v1.10.4` | 21.07. | **Fix Adress-Fallback** deterministisch aus min(xadr_id) statt rownum=1 (Finding 8) |
| `v1.10.5` | 21.08. | **Fehler-XML-Diagnose**: nicht bestandene XMLs (validator/kosit/xsd) landen zur Analyse in `xml_invalid/` samt `.error.txt`; geglückter Retry räumt auf |
| `v1.10.6` | 23.09. | **Fix BG-23-Abgleich** (BR-Z-01): fehlende Nullsteuer-Gruppen aus den Positionen ergänzen, Gruppen gleicher Kategorie/Satz zusammenfassen — Buchungen mit 0 % MwSt (CityTax/Kurtaxe) |

## Feld-Vorfall (behoben): BG-3 bei Gutschrift durch veralteten SQL-Override

**Symptom:** Validator meldet „Gutschrift braucht Bezug zur Original-Rechnung"
(BG-3), obwohl die Original-Rechnungsnummer (48400) korrekt und die Gutschrift
per Zahlungskommentar sauber verknüpft war.

**Diagnose-Kette (alles grün, außer dem Ergebnis):**
- VARCHAR-Falle ausgeschlossen: `zinv_number = '48400'` (String, exakt wie im
  Code) trifft die Rechnung — nur `= 48400` ohne Quotes wäre numerisch/tolerant.
- DB-Daten korrekt: die `ZPOS_CDT=5`-Zahlungszeile liefert den Kommentar `48400`.
- v1.10.5 aktiv: die neue `xml_invalid/`-Datei zeigte `<cbc:ID>None</cbc:ID>`
  → `billingreferenceid` kam leer (`None`) im Header an.

**Root Cause:** Eine **veraltete `slim/data/sql_overrides/invoice_header.sql`**
(aus der Zeit vor v1.10.0) überschattete via `_read_sql()` die Repo-SQL
**komplett** und unterschlug alle späteren Header-Fixes — u. a. `PaymentRefComment`
(v1.10.0, → BG-3-Fallback) **und** den Adress-Fallback `xadr_primary` (v1.10.4).
Ohne `PaymentRefComment` bekam der Fallback keinen Kommentar → Referenz blieb leer.

**Fix:** Instanz auf v1.10.5 aktualisiert, Override entfernt / auf Standard
gesetzt → Repo-SQL greift wieder (kein Dienst-Neustart nötig, `_read_sql` liest
pro Poller-Lauf frisch).

> **Betriebs-Lehre:** Fehlen in der XRechnung Felder (BG-3-Bezug, Kundenadresse
> u. a.), **zuerst `slim/data/sql_overrides/` prüfen** — ein alter Operator-Override
> überschattet Repo-Fixes still. Der Marker-Guard warnt im Log:
> „SQL-Override … wirkt veraltet — fehlende Marker: …" (`_EXPECTED_OVERRIDE_MARKERS`).

## Feld-Vorfall (behoben): BR-Z-01 bei Buchungen mit 0 % MwSt (CityTax)

**Symptom:** `zinv=739759` scheiterte an der KoSIT-Prüfung mit
„[BR-Z-01] … shall contain in the VAT breakdown (BG-23) **exactly one** VAT
category code (BT-118) equal with 'Zero rated'".

**Root Cause:** Die Steuerkategorie wird an zwei Stellen aus **unterschiedlichen
Quellen** abgeleitet:

| Quelle | Ableitung | Ergebnis bei 0 % |
|--------|-----------|------------------|
| `sql/invoice_lines.sql:32` | Steuersumme je `TAXLINK`; keine Steuerbuchung → `Z` | Position trägt `Z` |
| `sql/invoice_tax.sql` | baut **nur** aus Steuerbuchungen (`WHERE z.ZPOS_CDT IN (2)`), gruppiert je `ZTCD_ID` | **keine Gruppe** |

Für einen 0-%-Steuercode (CityTax, Kurtaxe, durchlaufende Posten) legt Suite8
gar keine Steuerbuchung an. Die Position trägt damit korrekt `Z`, in BG-23
entsteht dafür aber keine Zeile — genau das rügt BR-Z-01. Der Python-Layer
korrigierte bisher nur den Prozentsatz (`_normalize_tax_categories`, BR-Z-08)
und filterte 0/0-Zeilen (BR-CO-17); den Abgleich Positionen ↔ BG-23 machte
niemand.

**Fix (v1.10.6):** `_reconcile_vat_breakdown` in `modules/xml_builder.py`, in
`render()` nach Split/Positivierung eingehängt. Sie fasst Gruppen gleicher
(Kategorie, Satz) zusammen — deckt das *exactly one* ab, wenn zwei Steuercodes
denselben Satz haben — und ergänzt fehlende Nullsteuer-Gruppen (`Z, E, AE, G, K, O`)
aus den tatsächlich verwendeten Positions-/Allowance-Kategorien mit
`TaxableAmount` = Summe der Nettos und `TaxAmount` = 0.00. `S`-Gruppen werden
bewusst **nicht** neu erzeugt: dort ist der Steuerbetrag nicht eindeutig
ableitbar, und die Suite8-Rundung gegen Brutto soll unangetastet bleiben.

Nebeneffekt: der 0-%-Netto steckt via `invoice_totals.sql` bereits in BT-106,
fehlte aber in BG-23 — die ergänzte Zeile stellt damit auch BR-CO-13 wieder her.

**Verifikation:** gegen den echten KoSIT-Validator, gleiche Rechnung, nur der Fix
als Unterschied — ohne Fix BR-Z-01, mit Fix keine `BR-Z-*`/`BR-S-*`/`BR-CO-13/14/17`
mehr. Tests: `tests_slim/test_vat_breakdown_reconcile.py` (7 Fälle inkl.
Regressionswächter „7 % und 19 % dürfen nicht verschmelzen" und „Phantomgruppe
ohne Position bleibt gefiltert"), Gesamtsuite 265 passed / 1 skipped.

> **Offen (Gegenprüfung):** Die Ist-Daten zu `zinv=739759` konnten **nicht**
> geprüft werden — die von der Entwicklungsmaschine erreichbare V8LIVE-DB ist ein
> alter Abzug (letzte Rechnung `zinv_number` 144871 vom 04.04.2026). Der Fix ist am
> nachgebauten CityTax-Fall belegt, nicht an der Original-Rechnung. Nach dem
> Ausrollen einen Retry auf 739759 fahren und das Ergebnis hier nachtragen.

## Gutschriften/Stornorechnungen — Wege in Suite8 (Referenz, 08.09.2026)

Recherche gegen Suite8-Doku (Data Dictionary 8.10.2, Kassenmodul-Handbuch) und
Slim-Code, damit künftige BG-3-Vorfälle schneller einzuordnen sind.

**Erkennung durch Slim** (`invoice_fetcher.is_credit_note()`): `ZINV_ROLE` ∈ {3, 31}
**oder** Summe `LineExtensionAmountNet` aller Zeilen < 0. Laut Data Dictionary ist
`ZINV_ROLE`=3/31 an länderspezifische Fiskal-Integrationen gekoppelt (PL „Faktura
Korekta", IT „Fattura", TR/EG-Fiskalfelder) — für DE-Häuser vermutlich nie erfüllt;
maßgeblich ist praktisch nur die negative Zeilensumme.

**BillingReference (BG-3), zweistufig in `fetch_invoice()`:**
1. SQL (`sql/invoice_header.sql:23-26`): `orig.ZINV_ID = zinv.ZINV_VOID_ZINV_ID`.
2. Python-Fallback (`_resolve_billing_reference_from_payment`, nur bei 381 + Stufe 1
   leer): liest `ZPOS.ZPOS_COMMENT` der Zahlungszeile (`ZPOS_CDT=5`, verknüpft über
   `ZPIL.ZPIL_ZINV_ID`, neueste Zeile), extrahiert Ziffernfolgen, validiert gegen
   `ZINV_NUMBER` (Selbstbezug ausgeschlossen).

**Einziger in der Praxis bestätigter Weg:** negativer Buchungsbetrag im
Rechnungsfenster (Kasse → Rechnungen → Zahlung) **plus** Original-Rechnungsnummer
im Feld „Bemerkung" der Zahlungsbuchung. Design-Spec-Zitat (`docs/superpowers/specs/
2026-07-03-betriebs-haertung-design.md`): „Legt der Operator die Storno-/Gutschrift-
Rechnung in Suite8 ohne diesen Bezug an, bleibt das Feld leer … In der Hotel-Praxis
trägt der Operator die Original-Rechnungsnummer stattdessen als Freitext in den
Kommentar der Zahlungszeile ein." — d. h. `ZINV_VOID_ZINV_ID` wird in der Praxis
erkennbar nicht zuverlässig gepflegt.

**Ungeklärt/nicht code-verifiziert:** ob die Suite8-Funktion „Rechnung ungültig
machen" (`Kasse → Rechnungen → Optionen → Ungültige Rechnung`, Parameter
„Handhabung ungültiger Rechnungen" unter Länderspezifisch 2) `ZINV_VOID_ZINV_ID`
setzt — Handbuch verortet die Funktion primär bei Ländern mit fiskalischem
Neudruckverbot, nicht bestätigt für DE. Ebenso ungeklärt: „Debit. zuweisen"
(Kasse → Debitorenverwaltung, Guest-Ledger-Häuser).

**Mitgeholt, aber ungenutzt** in `invoice_header.sql:109`: `ZINV_CORRECTING_ZINV_ID`,
`ZINV_VOID_REASON`, `ZINV_EXPORTSTATUS`, `ZINV_FISCALNUMBER`, `ZINV_FISCALINVOICE`,
`ZINV_NUMBER2`, `ZINV_MANUALNUMBER`, `ZINV_CITYLEDGERNUMBER` — Altlast aus der
Original-View, in keiner Bezugs-/Credit-Note-Logik ausgewertet.

## Einbindungshandbuch (nicht-technisch, für IT/DBA/Front Office)

Unter `docs/handbuch/` (lokal, noch **nicht** committet — siehe Git-Stand):
`XRechnung_Slim_Handbuch.html` (per Doppelklick im Browser zu öffnen, kein
claude.ai-Login nötig) und `XRechnung_Slim_Handbuch.odt` (Word/LibreOffice).
Zusätzlich als Online-Artifact veröffentlicht (privat, im aktuellen Chat-Verlauf
verlinkt). Inhalt: Software-Zweck, Wahl des Installationsrechners (Empfehlung
Interface-PC/Server + GitHub-Internetzugang), Setup-Assistent, Suite8-seitige
Voraussetzungen mit konkreten Klickpfaden (Kassenmodul/Kundenverwaltung statt
DB-Feldnamen), Backend-/Netzwerkzugriff für andere PCs, Troubleshooting.

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

- [ ] **Template-Kosmetik `creditnote_3.0.xml.j2:28`:** Bei leerem
      `billingreferenceid` rendert `{{ header.billingreferenceid|e }}` das Wort
      `None` statt eines leeren Elements (`<cbc:ID>None</cbc:ID>`). Fällt im
      Normalbetrieb nie auf (Validator bricht vorher ab), nur in der v1.10.5-
      Diagnose-XML sichtbar. Kleiner TDD-Fix (leeres Feld → wirklich leer).
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

- `python -m pytest tests_slim/` → **258 passed, 1 skipped** (Live-DB-Integration).

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
- `docs/handbuch/` — nicht-technisches Einbindungshandbuch (HTML + ODT), noch nicht committet
- `docs/superpowers/specs/2026-07-03-betriebs-haertung-design.md` — Design-Spec v1.10.0
- `INSTALL_FROM_GITHUB.md` / `RELEASE_CHECKLIST.md` — Install- / Release-Anleitung

## Release-How-To (kurz, aus dieser Serie bewährt)

1. `VERSION` bumpen, STATUS.md nachziehen, committen.
2. `git tag -a vX.Y.Z -m "..."`, `git push origin master`, `git push origin vX.Y.Z`.
3. GitHub-Release: `gh` ist auf diesem Host **nicht** installiert → Helper-Skript
   `scripts/gh_release.sh vX.Y.Z "vX.Y.Z — Titel" notes.md` (REST-API, Token aus
   `git credential fill`, Repo aus origin-Remote).
4. Verifizieren: `releases/latest` meldet den neuen Tag (was der Auto-Updater abfragt).

## Git-Stand

- Branch `master`, aktuelles Release/Tag `v1.10.5` (21.08.2026, Fehler-XML-
  Diagnose in `xml_invalid/`). Code-Arbeitsbaum sauber, alles gepusht.
- Offen (unstaged, kein Code): `docs/handbuch/` (Handbuch HTML+ODT) sowie diese
  STATUS.md-Aktualisierung — bewusst noch nicht committet, da rein redaktionell
  und nicht mit dem Nutzer abgestimmt, ob das Handbuch ins öffentliche Repo soll.
- Tag-Kette: `v1.10.5` → `v1.10.4` → `v1.10.3` → `v1.10.2` → `v1.10.1` → `v1.10.0` → `v1.9.0` @ `1b419bf`.
