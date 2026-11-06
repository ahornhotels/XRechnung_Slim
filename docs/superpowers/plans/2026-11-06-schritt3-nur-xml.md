# Schritt 3: Nur-XML-Versand – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Bei Kunden mit dem Membership „PDF“, oder wenn der globale Schalter „Nur XML für alle“ an ist, enthält die Rechnungsmail nur die XRechnung.

**Architecture:** `fetch_invoice` ermittelt `invoice["xml_only"]` (`None`, `"membership"` oder `"global"`). Dazu dient eine eigene Abfrage, nicht die Kopf-SQL, damit SQL-Overrides unberührt bleiben. `attach_xml_to_wmai(..., remove_pdf=True)` leert in derselben Transaktion den PDF-Hauptanhang der Mail (`WMAI_ATTACHMENT_WTXT_ID` und `WMAI_ATTACHMENT_FILE_NAME`), bevor es entblockt. Poller und `run_now` reichen den Wert durch und protokollieren ihn.

**Spec:** `docs/superpowers/specs/2026-11-06-slim-umbau-design.md`, Abschnitt 8.

## Global Constraints

- Gelöscht wird nichts. `WTXT` wird nie angefasst, nur der Verweis in der WMAI wird geleert.
- Bedingungen für das Leeren: `WMAI_BLOCKSEND=1`, `WMAI_SENT=0`, `lower(WMAI_ATTACHMENT_FILE_NAME) LIKE '%.pdf'` und `WMAI_ATTACHMENT_RTF_WTXT_ID IS NULL`.
- Ändert das Update 0 Zeilen, geht die Mail trotzdem mit der XML hinaus, mit Warnung im Audit (`pdf_not_removed`). Die Rechnung wird nicht blockiert.
- Membership: `XMNR` → `XMTY` mit `upper(XMTY_SHORTDESC) = upper(<konfiguriert>)`, Standard `PDF`. Geprüft wird am Profil `ZWIN_INVOICE_TO_XCMS_ID` oder `ZINV_XCMS_ID`.
- Konfiguration in `hotel.json`:
  - `xml_only_all` (bool, Standard `false`)
  - `xml_only_membership` (str, Standard `"PDF"`; leer bedeutet, keine Membership-Prüfung)
- Fehlt eine Spalte oder Tabelle (ORA-00904/00942), läuft der Versand wie bisher mit PDF weiter, und Slim warnt einmal.
- Tests wie in Schritt 1. Nach jeder Aufgabe `/code-review high`.

## Review Focus

1. **Mail ohne PDF-Hauptanhang:** Die XML wird angehängt, nichts scheitert, und das Audit meldet „PDF nicht entfernt“ (Task 1).
2. **Mail mit RTF-Anhang:** Das PDF bleibt, eine Warnung wird protokolliert (Task 1).
3. **Fehler in der Membership-Abfrage:** Die Mail geht mit PDF hinaus, die Rechnung wird nicht blockiert (Task 2).
4. **Globaler Schalter aus und kein Membership:** Verhalten exakt wie bisher, ohne zusätzliches UPDATE (Task 1).

---

### Task 1: `attach_xml_to_wmai(..., remove_pdf: bool = False) -> dict`

**Files:** `modules/suite8_mailer.py`, Test `tests_slim/test_xml_only_attach.py`

- Rückgabe ergänzt um `"pdf_removed": bool`.
- Das UPDATE steht vor dem Entblocken und nur bei `remove_pdf=True`.
- Tests mit Fake-Connection, die die SQL-Aufrufe aufzeichnet:
  - `test_ohne_remove_pdf_kein_update`
  - `test_remove_pdf_leert_verweis_vor_entblocken`: Reihenfolge, Bedingungen im SQL, kein DELETE und kein `WTXT`-UPDATE
  - `test_remove_pdf_null_zeilen_kein_fehler`: Ergebnis `pdf_removed=False`, Commit erfolgt
  - `test_fehler_beim_leeren_rollback`

### Task 2: Ermittlung `xml_only`

**Files:** `modules/invoice_fetcher.py` (`_xml_only_reason(cur, zinv_id) -> str | None`, Aufruf in `fetch_invoice`), `slim/config/hotel.json.example`, Test `tests_slim/test_xml_only_reason.py`

- Ist `xml_only_all` an, gilt `"global"`, ohne DB-Abfrage.
- Sonst prüft eine Abfrage das Membership mit Bind `:code`. Gibt es einen Treffer, gilt `"membership"`.
- Bei leerem Code gibt es keine Abfrage.
- Bei einem DB-Fehler gibt es `None`, und Slim warnt einmal pro Prozess.

### Task 3: Poller und run_now

**Files:** `slim/jobs_slim/poller.py`, `slim/api_slim/run_now.py`, Tests in `tests_slim/test_xml_only_attach.py`

- Übergeben wird `remove_pdf=bool(inv.get("xml_only"))`.
- Audit `attach_ok.details`:
  - `"xml_only": reason`
  - `"pdf_removed": bool`
  - bei `xml_only` ohne Entfernung zusätzlich `"pdf_not_removed": true`

### Task 4: Abschluss

Gesamtsuite, STATUS.md. Hinweis an den Nutzer: Erster Echttest an **einem** Haus mit **einem** Testkunden. Prüfen, ob Suite8 die Mail ohne Hauptanhang versendet.
