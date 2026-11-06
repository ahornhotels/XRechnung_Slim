# Schritt 2: Auslagen – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Auslagen ohne Steuerzeile blockieren keine Rechnung mehr und gehen als Z 0 % in Positionen, Steuergruppen und Summen ein. Paid-Out wird nach Entscheidung des Nutzers betragsgenau abgebildet.

**Architecture:** Der Steuersatz einer Leistungszeile ohne CDT-2-Partner wird in allen drei Kopien der Zeilenlogik (`invoice_lines.sql`, CTEs in `invoice_tax.sql` und `invoice_totals.sql`) zu 0. Der Divergenz-Guard (`tests_slim/test_sql_templates.py::test_zeilenlogik_synchron_ueber_drei_sql`) wird um das neue Fragment erweitert. Die Z-Gruppe in BG-23 ergänzt schon heute `xml_builder._reconcile_vat_breakdown`.

**Tech Stack:** Oracle-SQL, Python 3.12, pytest, KoSIT lokal.

**Spec:** `docs/superpowers/specs/2026-11-06-slim-umbau-design.md`, Abschnitt 7.

## Global Constraints

- Wie in Plan Schritt 1: öffentliches Repo ohne echte Daten, nur SELECT, Testbefehl `C:\FIDELIO\Suite8XRechnung\.venv\Scripts\python.exe -m pytest tests_slim -q`, KoSIT nur mit den Stammdatenbefunden R020/R010/BR-DE-6/7.
- Befund aus SHT (Live, nur SELECT): Leistungszeilen ohne CDT-2 ergeben heute `ClassifiedTaxCategoryPercent` = NULL. Damit wird auch `LineExtensionAmountNet` NULL, und der Validator meldet „USt-Satz nicht ermittelbar“. Betroffen sind rund 5.300 Rechnungen pro Jahr.
- Eine Zeile **mit** CDT-2-Partner, deren Satz sich nicht ermitteln lässt, bleibt NULL und blockiert. Das ist ein echter Datenfehler.
- Nach `/code-review high` je Aufgabe werden die Befunde wie in Schritt 1 behandelt.

## Review Focus

1. **Rechnung mit Z-Auslage neben 19 % und 7 %:** BG-23 enthält genau eine Z-Gruppe mit der Summe der Auslagen, und BT-106, BT-109 und BT-112 gehen auf (Task 1, KoSIT-Gegenprobe).
2. **Negative Z-Auslage (Korrektur):** Sie wird zum Abschlag mit Kategorie Z 0 %, BR-Z-01 bleibt grün (Task 1).
3. **Kurtaxe mit MS0-Partner:** unverändert Z 0 % (Task 1, Regressionstest).
4. **Rechnung mit Paid-Out:** Brutto, Positionen und Zahlbetrag passen zueinander (Task 2, nach Entscheidung).

---

### Task 1: Z 0 % für Leistungszeilen ohne Steuerzeile

**Files:**
- Modify: `sql/invoice_lines.sql`, `sql/invoice_tax.sql`, `sql/invoice_totals.sql`. In jeder Kopie wird der Ausdruck `ClassifiedTaxCategoryPercent` ersetzt.
- Modify: `tests_slim/test_sql_templates.py`: neues Fragment im Guard
- Test: `tests_slim/test_auslagen_ohne_steuer.py`

**Ausdruck, identisch in allen drei Dateien:**

```sql
nvl((select evaluatemath(replace((replace(ztcd_udf,'x',100)),';',',')) from zpos Z2,ztcd where Z2.zpos_taxlink_id=z.zpos_taxlink_id and Z2.zpos_cdt=2 and Z2.zpos_ztcd_id=ztcd.ztcd_id),
    (select 0 from dual where not exists (select 1 from zpos Z3 where Z3.zpos_taxlink_id=z.zpos_taxlink_id and Z3.zpos_cdt=2)))  ClassifiedTaxCategoryPercent
```

- [ ] **Step 1: Failing tests.**
  - `test_satz_ohne_steuerzeile_ist_null_prozent_in_allen_drei_sql`: das Fragment `not exists (select 1 from zpos Z3 ...)` steht in allen drei Dateien.
  - `test_z_auslage_wird_nicht_geblockt`: Validator ohne `tax_percent`-Fehler bei Z mit Satz `"0"`.
  - `test_xml_z_auslage_neben_19_und_7`: Render ergibt BG-23 mit genau einer Z-Gruppe (taxable = Auslagensumme, Steuer 0.00) und ist XSD-gültig.
  - `test_negative_z_auslage_wird_abschlag_z`: Die negative Auslage erscheint als `AllowanceCharge` mit Kategorie Z und Percent 0.
- [ ] **Step 2:** Die Tests laufen und schlagen fehl (SQL-Fragment fehlt). Der Render-Test darf schon grün sein, wenn der Builder das bereits kann. Das wird im Ledger vermerkt.
- [ ] **Step 3:** SQL in allen drei Dateien ändern, Guard-Fragment ergänzen.
- [ ] **Step 4:** Gesamtsuite grün. KoSIT-Gegenprobe mit einer Rechnung nach dem Muster der SHT-Rechnung „Auslage ohne Steuer“: Positionen zu 19 % und 7 % plus fünf Auslagen über zusammen 15,00 €. Erwartet: keine Befunde außer Stammdaten.
- [ ] **Step 5:** Commit `fix(sql): Leistungen ohne Steuerzeile als Z 0 % statt Satz NULL`, danach `/code-review high`.

### Task 2: Paid-Out (CDT 5, `ZPOS_PAIDOUT=1`)

**Befund in SHT:**
- Paid-Out ist eine negative CDT-5-Zeile, z. B. -7,65 € oder -25,00 € mit dem Artikel „Auslagen“.
- `invoice_totals.sql` zählt sie ins Brutto: `-gross`, also +7,65 €.
- Die Positionen (nur CDT 1) enthalten sie nicht. Brutto (BT-112) ≠ Netto + Steuer, das ergibt einen KoSIT-Fehler (BR-CO-15).

**Entscheidung des Nutzers nötig.** Zwei Lesarten:
- (a) **Auslage für den Gast** (der Betrieb hat für den Gast bezahlt): Sie wird eine Position „Auslage“ mit Z 0 % und positivem Betrag. Das Brutto enthält sie, wie OPERA.
- (b) **Barauszahlung an den Gast** (Cash-back auf Karte): Sie ist keine Rechnungsposition. Das Brutto wird ohne sie berechnet. Der Mehrbetrag der Kartenzahlung gehört dann nicht zur Rechnung.

Nach der Entscheidung wird diese Aufgabe mit Tests konkretisiert. Bis dahin ändert sich am Paid-Out nichts.

### Task 3: Abschluss

- [ ] Gesamtsuite, Durchsicht auf echte Daten, STATUS.md, Bericht an den Nutzer.
