# Menü, XRechnung-Schalter, BT-10-Freitexte, Archiv – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slim bekommt eine Menüleiste mit getrennten Seiten (Konfiguration XRechnung, Hoteldaten, Archiv, System), einen Ein-/Ausschalter, der den Suite8-Trigger in der DB schaltet, wählbare Freitexte als BT-10-Ersatz und ein Archiv für Prüfer.

**Architecture:** Der Triggerzustand wird nie gespeichert, sondern immer aus `ALL_TRIGGERS` gelesen (neues Modul `trigger_state`). Die Einstellungsseite bleibt eine generische Seite (`settings.html`), die per URL nur die Abschnitte ihres Menüpunkts zeigt; jeder Abschnitt im Schema bekommt ein Feld `page`. Ein gemeinsames `nav.js` setzt Menü und Schalter auf jede Seite. Das Archiv bekommt je XML eine Seitendatei `<stem>.meta.json`; Bestandsdateien werden beim ersten Listen einmalig nachgetragen.

**Tech Stack:** Python 3.12, FastAPI, python-oracledb, Jinja2, Vanilla-JS/HTML, pytest.

**Spec:** `docs/superpowers/specs/2026-11-16-menue-schalter-archiv-design.md`

## Global Constraints

- Tests: `C:\FIDELIO\Suite8XRechnung\.venv\Scripts\python.exe -m pytest tests_slim -q -p no:cacheprovider` – Ausgangsstand 547 passed, 1 skipped; am Ende alles grün.
- Repo ist öffentlich: keine Hausnamen, echten Rechnungsnummern, Kundendaten in Code, Tests, Doku.
- Datenbank in Tests nie echt ansprechen (Fake-Cursor / MagicMock wie in `tests_slim/test_xml_only_reason.py`, `tests_slim/test_poller_loop.py`).
- Oberflächentexte Deutsch mit Umlauten; Code-Kommentare wie im Bestand.
- Triggername fest: `WMAI_XRECHNUNG_BLOCK`, Tabelle `WMAI` (aus `slim/api_slim/trigger_sql.py`).
- `test_jeder_json_schluessel_in_der_oberflaeche` gilt weiter; einzige neue Ausnahme ist `mail_strategy`.
- Kein Commit/Push auf `master`; gearbeitet wird auf Branch `feat/menue-schalter-archiv`.

## Review Focus

1. Slim-Benutzer ist nicht Besitzer von `WMAI` bzw. des Triggers → Anzeige „nicht prüfbar“, nie „fehlt“, Poller arbeitet weiter.
2. `ALTER TRIGGER` scheitert (ORA-01031) → Zustand unverändert, Meldung im Klartext, Audit mit Fehler.
3. Rechnung mehrfach archiviert (Retry) → jede Version behält ihren eigenen SHA-256 und ihre eigenen Metadaten; Echtheit der alten Version bleibt „unverändert“.
4. Archiv-Datei, die angehängt wurde, deren Anhängen aber scheiterte → Status „nicht angehängt“, nicht „gesendet“.
5. BT-10: DXR-Mitgliedschaft gefüllt **und** Freitext eingeschaltet → DXR gewinnt; Override aus der Mail-Korrektur gewinnt weiterhin über beides.

---

### Task 1: Triggerzustand lesen und schalten

**Files:**
- Create: `slim/core_slim/trigger_state.py`
- Create: `slim/api_slim/schalter_api.py`
- Modify: `slim/main_slim.py` (Router einhängen)
- Test: `tests_slim/test_trigger_state.py`, `tests_slim/test_schalter_api.py`

**Interfaces:**
- Produces:
  - `trigger_state.TRIGGER_NAME = "WMAI_XRECHNUNG_BLOCK"`
  - `trigger_state.read_state(conn) -> dict` mit Schlüsseln `state` (`"aktiv" | "inaktiv" | "fehlt" | "nicht_pruefbar"`), `owner: str|None`, `user: str|None`, `grant_sql: str|None`, `error: str|None`
  - `trigger_state.set_enabled(conn, enabled: bool) -> dict` (liefert danach `read_state(conn)`; wirft `TriggerSchaltFehler(str)` mit Oracle-Text)
  - `GET /api/schalter` → `read_state` (Rolle ansehen erlaubt), `POST /api/schalter` Body `{"ein": bool}` (nur verwalten, über bestehende Regel „nicht-GET = verwalten“ in `auth_api._needs_admin`)
  - Audit-Event `"schalter_geaendert"` mit `details={"by", "vorher", "nachher"}` bzw. zusätzlich `"error"`

Ablauf `read_state`:
1. `SELECT USER FROM dual`.
2. Besitzer von `WMAI` ermitteln: `all_tables` mit `table_name='WMAI'`; gibt es eine Zeile mit `owner = USER`, gilt die, sonst über `all_synonyms` (`synonym_name='WMAI'`, `owner IN (USER,'PUBLIC')`) → `table_owner`.
3. `SELECT owner, status FROM all_triggers WHERE trigger_name=:n AND table_name='WMAI' AND table_owner=:o`.
4. Zeile da → `ENABLED`→aktiv, `DISABLED`→inaktiv. Keine Zeile → `fehlt` nur wenn `wmai_owner == USER`, sonst `nicht_pruefbar`. Jede Exception → `nicht_pruefbar` mit `error`.
5. `grant_sql = f"GRANT ALTER ANY TRIGGER TO {user};"` nur wenn Trigger-Besitzer ≠ `USER`.

`set_enabled`: nur bei Zustand aktiv/inaktiv; Besitzer gegen `^[A-Z0-9_$#]{1,128}$` prüfen, dann `ALTER TRIGGER "<owner>"."WMAI_XRECHNUNG_BLOCK" ENABLE|DISABLE`. Bei `fehlt`/`nicht_pruefbar` → `TriggerSchaltFehler("Trigger fehlt …" / "nicht prüfbar …")`.

- [ ] **Step 1: Tests schreiben** (`tests_slim/test_trigger_state.py`, Fake-Cursor mit Antworten je SQL-Teilstring)

```python
def test_aktiv_eigener_trigger(): assert read_state(conn(user="V8LIVE", wmai_owner="V8LIVE", trig=("V8LIVE","ENABLED")))["state"] == "aktiv"
def test_inaktiv(): ... trig=("V8LIVE","DISABLED") -> "inaktiv"
def test_fehlt_nur_wenn_eigene_tabelle(): trig=None, wmai_owner=user -> "fehlt"
def test_fremde_tabelle_ohne_sicht_ist_nicht_pruefbar(): user="SLIM", wmai_owner="V8LIVE", trig=None -> "nicht_pruefbar"
def test_fremder_trigger_liefert_grant(): user="SLIM", trig=("V8LIVE","ENABLED") -> grant_sql == "GRANT ALTER ANY TRIGGER TO SLIM;"
def test_db_fehler_ist_nicht_pruefbar(): cursor wirft -> state "nicht_pruefbar", error gesetzt
def test_schalten_sql(): set_enabled(c, False) führt 'ALTER TRIGGER "V8LIVE"."WMAI_XRECHNUNG_BLOCK" DISABLE' aus
def test_schalten_fehlt_wirft(): Zustand fehlt -> TriggerSchaltFehler, kein ALTER ausgeführt
def test_besitzer_mit_sonderzeichen_wird_abgelehnt(): owner='X"; DROP' -> TriggerSchaltFehler, kein ALTER
```

`tests_slim/test_schalter_api.py` (Router mit gepatchtem `get_connection` und `trigger_state`):

```python
def test_get_liefert_zustand(): GET /api/schalter -> {"state": "aktiv", ...}
def test_post_schaltet_und_auditiert(tmp_path): POST {"ein": False} -> 200, Audit schalter_geaendert vorher aktiv nachher inaktiv, by=Benutzer
def test_post_fehler_409_mit_meldung_und_audit(): set_enabled wirft TriggerSchaltFehler("ORA-01031") -> 409, detail enthält "ORA-01031", Audit mit error
def test_post_ohne_bool_422(): {"ein": "ja"} -> 422
```

- [ ] **Step 2: Tests laufen lassen** – Expected: FAIL (`ModuleNotFoundError: slim.core_slim.trigger_state`)
- [ ] **Step 3: Implementieren** (`trigger_state.py`, `schalter_api.py` mit `router = APIRouter(prefix="/api/schalter")`, in `main_slim.py` einhängen)
- [ ] **Step 4: Tests laufen lassen** – Expected: PASS; ganze Suite grün
- [ ] **Step 5: Commit** `feat(schalter): Triggerzustand lesen und schalten`

### Task 2: Poller und Status richten sich nach dem Trigger

**Files:**
- Modify: `slim/jobs_slim/poller.py` (nach der `mail_strategy`-Prüfung, vor `find_pending_wmai`)
- Modify: `slim/api_slim/status.py` (Warnung + Feld `trigger`)
- Test: `tests_slim/test_poller_loop.py`, `tests_slim/test_api_endpoints.py` (bzw. wo `/api/status` getestet wird)

**Interfaces:**
- Consumes: `trigger_state.read_state(conn)` (Task 1)
- Produces: Poller-Summary-Schlüssel `"skipped_trigger": bool`; `/api/status` liefert zusätzlich `"trigger": <read_state>`

Regel: Nur `state == "inaktiv"` hält den Poller an (`skipped_trigger: True`, nichts angefasst, keine WMAI-Fehler geschrieben). `fehlt`/`nicht_pruefbar` → weiter wie heute. Audit-Event `"poller_pausiert_trigger"` nur beim Wechsel in den Zustand (Modulvariable mit letztem Zustand), nicht in jedem Lauf.

- [ ] **Step 1: Tests**

```python
def test_trigger_inaktiv_haelt_poller_an(tmp_path, mocked_db):  # patch read_state -> inaktiv
    s = poller.run_once(data_dir=tmp_path); assert s["skipped_trigger"] is True and s["attached"] == 0
    # find_pending_wmai wurde nicht aufgerufen
def test_trigger_nicht_pruefbar_arbeitet_weiter(...): read_state -> nicht_pruefbar, find_pending aufgerufen
def test_trigger_fehlt_arbeitet_weiter(...)
def test_pausiert_audit_nur_beim_wechsel(...): zwei Läufe inaktiv -> genau ein Audit poller_pausiert_trigger
def test_status_warnt_bei_inaktivem_trigger(): /api/status -> warnings enthält "XRechnung ist ausgeschaltet"
```

Bestehende Poller-Tests bleiben unverändert grün (MagicMock-Verbindung darf nicht als „inaktiv“ gelesen werden).

- [ ] **Step 2: Tests laufen lassen** – Expected: FAIL (`KeyError: 'skipped_trigger'`)
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: Tests laufen lassen** – Expected: PASS, Suite grün
- [ ] **Step 5: Commit** `feat(poller): bei ausgeschaltetem Trigger keine Verarbeitung`

### Task 3: Einstellungen nach Menüpunkten, BT-10-Schalter im Schema

**Files:**
- Modify: `slim/core_slim/settings_schema.py`, `slim/api_slim/settings_api.py`, `slim/config/hotel.json.example`
- Test: `tests_slim/test_settings_api.py`

**Interfaces:**
- Produces:
  - `Section.page: str` (`"xrechnung" | "hotel" | "system"`)
  - `GET /api/settings?page=<page>` filtert; ohne `page` alle Abschnitte (bestehende Tests)
  - Antwort je Abschnitt zusätzlich `"page"`
  - Neue Schlüssel in `hotel.json`: `bt10_freitext1` … `bt10_freitext4` (bool, Standard `False`)

Neue Aufteilung (Abschnitts-IDs fest, Tests nutzen sie):

| page | id | label | Schlüssel |
|---|---|---|---|
| xrechnung | `erkennung` | Erkennung und Anhang | suite8_recognize_subject_pattern, suite8_recognize_filename_pattern, suite8_attachment_name_template, xml_only_all, xml_only_membership |
| xrechnung | `inhalt` | Rechnungsinhalt | gastzeile, positionen_zusammenfassen, auslagen_artikel, rundungsausgleich |
| xrechnung | `kaeuferreferenz` | Käuferreferenz (BT-10) | bt10_freitext1 … 4 |
| xrechnung | `pruefung` | Prüfung | kosit_validation, xrechnung_version |
| hotel | `hotel` | Haus | hotel_code, hotel_long_name, currency, default_payment_terms_days |
| hotel | `ansprechpartner` | Ansprechpartner und Absender | seller_contact_name, seller_contact_phone, seller_contact_email, absender_email |
| system | `datenbank` | Datenbank (Suite8) | wie heute |
| system | `abruf` | Abruf | suite8_poll_interval_seconds |
| system | `server` | Server | wie heute |
| system | `update` | Update | wie heute |

`mail_strategy` fällt aus dem Schema. Die Regel „mindestens ein Erkennungsmuster“ in `_put_section` hängt dann an `erkennung` statt `versand`.

Texte (exakt, als `help` bzw. `info`):
- `bt10_freitext1` Label „Freitext 1“, help: „Erscheint immer als Hinweis (BT-22) in der XRechnung, eingeschaltet zusätzlich als Käuferreferenz.“
- `bt10_freitext2..4` Label „Freitext N“, help: „Erscheint nur in der XRechnung, wenn hier eingeschaltet – dann als Käuferreferenz.“
- alle vier `info` = gemeinsamer HTML-Text `_INFO_BT10` mit: Reihenfolge („Die DXR-Mitgliedschaft am Rechnungsempfänger hat immer Vorrang. Danach gilt der erste gefüllte eingeschaltete Freitext, in der Reihenfolge 1 → 4. Ist keiner gefüllt, steht wie bisher der Name des Profils in BT-10.“) und Fundort („In Suite8: Rechtsklick im Rechnungsfenster → „Bearbeite gewähltes Fenster“ → Reiter „Text“. Die vier Zeilen dort sind Freitext 1 bis 4.“)

- [ ] **Step 1: Tests anpassen/ergänzen**

```python
def test_seiten_aufteilung():
    pages = {s.id: s.page for s in settings_schema.SECTIONS}
    assert pages == {"erkennung": "xrechnung", "inhalt": "xrechnung", "kaeuferreferenz": "xrechnung", "pruefung": "xrechnung",
                     "hotel": "hotel", "ansprechpartner": "hotel",
                     "datenbank": "system", "abruf": "system", "server": "system", "update": "system"}
def test_api_filtert_nach_seite(env): ids von GET /api/settings?page=hotel == ["hotel", "ansprechpartner"]
def test_bt10_freitexte_standard_aus_und_erklaert(env): 4 Felder bool, value False, info enthält "DXR", "1 → 4", "Bearbeite gewähltes Fenster", "Text"
def test_freitext1_hinweis_text(): help von bt10_freitext1 enthält "immer als Hinweis (BT-22)"
def test_mail_strategy_nicht_mehr_in_oberflaeche(): kein Setting mit key mail_strategy
```

Bestehende Tests: `versand` → `erkennung` (Muster) bzw. `ansprechpartner` (absender_email); `test_verarbeitung_pausierbar` entfällt (ersetzt durch obigen Test); `_NICHT_IM_SCHEMA = {"seller_overrides", "mail_strategy"}`.

- [ ] **Step 2: Tests laufen lassen** – Expected: FAIL (`AttributeError: 'Section' object has no attribute 'page'`)
- [ ] **Step 3: Implementieren** (+ `hotel.json.example` bekommt `bt10_freitext1..4: false`)
- [ ] **Step 4: Tests** – Expected: PASS, Suite grün
- [ ] **Step 5: Commit** `feat(settings): Einstellungen nach Menüpunkten, BT-10-Freitexte`

### Task 4: BT-10 aus Freitext 1–4

**Files:**
- Modify: `modules/invoice_fetcher.py`
- Test: `tests_slim/test_bt10_freitext.py`

**Interfaces:**
- Consumes: hotel.json `bt10_freitext1..4` (Task 3)
- Produces: `invoice_fetcher._bt10_freitexte() -> list[int]` (eingeschaltete Nummern, aufsteigend), `invoice_fetcher._buyer_reference_aus_freitext(cur, zinv_id: int, aktiv: list[int]) -> Optional[str]`

Eigene kleine Abfrage (nicht `invoice_header.sql` ändern – SQL-Overrides der Häuser würden sie sonst überschatten):

```sql
select (select max(xmnr_value) from xmnr, xmty
         where xmnr_xmty_id = xmty_id and xmty_shortdesc = 'DXR'
           and xmnr_xcms_id = zwin_invoice_to_xcms_id) dxr,
       zwin_freetext1, zwin_freetext2, zwin_freetext3, zwin_freetext4
  from zinv, zwin where zinv_zwin_id = zwin_id and zinv_id = :zinv_id
```

Regeln: `aktiv` leer → keine Abfrage, `None`. DXR nicht leer → `None` (Header bleibt). Sonst erster eingeschalteter, nach `strip()` nicht leerer Freitext. Abfragefehler → Warnung einmal loggen, `None`. In `fetch_invoice` direkt nach `_apply_seller_overrides(header)`: Wert gesetzt → `header["buyerreference"] = wert`. Freitext 1 bleibt unverändert `Note`.

- [ ] **Step 1: Tests**

```python
def test_dxr_hat_vorrang(): row=("LEITWEG-1","A","B",None,None), aktiv=[1,2] -> None
def test_erster_gefuellter_in_reihenfolge(): row=(None,"  ","B","C",None), aktiv=[1,2,3] -> "B"
def test_nur_eingeschaltete(): row=(None,"A","B",None,None), aktiv=[2] -> "B"
def test_keiner_gefuellt(): -> None
def test_nichts_aktiv_keine_abfrage(): aktiv=[] -> None, cur.calls == []
def test_sql_bindet_zinv_id_und_nutzt_dxr(): params == {"zinv_id": 7}, sql enthält "xmty_shortdesc = 'DXR'" und "zwin_freetext4"
def test_abfragefehler_ergibt_none(caplog)
def test_einstellung_lesen(monkeypatch): hotel {"bt10_freitext3": True, "bt10_freitext1": True} -> [1, 3]
def test_fetch_invoice_setzt_buyerreference(monkeypatch): Fake-Verbindung, Header buyerreference "Name" -> nach fetch "B"
```

- [ ] **Step 2: Tests laufen lassen** – Expected: FAIL (`AttributeError: _buyer_reference_aus_freitext`)
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: Tests** – Expected: PASS, Suite grün
- [ ] **Step 5: Commit** `feat(bt10): Freitext 1–4 als Ersatz nach der DXR-Mitgliedschaft`

### Task 5: Archiv-Metadaten je XML

**Files:**
- Modify: `slim/core_slim/archive_fs.py`, `slim/jobs_slim/poller.py`
- Create: `slim/core_slim/xml_fakten.py`
- Test: `tests_slim/test_archive_fs.py`, `tests_slim/test_xml_fakten.py`, `tests_slim/test_poller_loop.py`

**Interfaces:**
- Produces:
  - `xml_fakten.lies(xml_bytes: bytes) -> dict` mit `rechnung` (cbc:ID), `rechnungsdatum` (IssueDate, `YYYY-MM-DD`), `art` (`"Rechnung"` bei Root `Invoice`, `"Gutschrift"` bei `CreditNote`), `betrag` (PayableAmount als str), `waehrung`, `kaeufer` (Buyer RegistrationName bzw. Name). Ungültige XML → `{}`.
  - `archive_fs.save_xml(..., meta: Optional[dict] = None)` schreibt `<stem>.meta.json` = `xml_fakten.lies(xml) | meta | {"status": "archiviert", "archiviert_am": iso}`
  - `archive_fs.mark_sent(xml_path: str, wmai_id: int, empfaenger: str, now=None) -> None` setzt `status="gesendet"`, `angehaengt_am`, `wmai_id`, `empfaenger`
  - `archive_fs.ensure_meta(xml_path: Path, sent_index: dict) -> dict` liest bzw. legt einmalig die Seitendatei für Bestandsdateien an (Status aus `sent_index`)
  - `archive_fs.sent_index(data_dir) -> dict[str, dict]` aus allen `audit-*.jsonl`: `attach_ok`-Einträge, Schlüssel = normalisierter `details.xml_path`, Wert `{"angehaengt_am": ts, "wmai_id": ...}`
- Versionierung: Beim Umbenennen einer vorhandenen XML zu `<stem>.<ts>.xml` werden `.sha256` und `.meta.json` mit demselben `<ts>` mit umbenannt (heute wird die `.sha256` überschrieben – Fehler, Review Focus 3). Die umbenannte `.sha256` bekommt den neuen Dateinamen in der Zeile.
- Poller: `save_xml(..., meta={"wmai_id": wmai_id, "empfaenger": row["to"]})`; nach `attach_ok` `mark_sent(arch["xml_path"], wmai_id, row["to"])` in `try/except` (Fehler nur loggen).

- [ ] **Step 1: Tests**

```python
def test_fakten_rechnung(): Beispiel-XML aus Test-Fixture -> art "Rechnung", rechnungsdatum "2026-11-14", betrag
def test_fakten_gutschrift(): CreditNote -> art "Gutschrift"
def test_fakten_kaputte_xml(): b"<x" -> {}
def test_save_xml_schreibt_meta(tmp_path): status "archiviert", rechnung, empfaenger
def test_mark_sent(tmp_path): status "gesendet", angehaengt_am gesetzt
def test_version_behaelt_eigenen_hash(tmp_path): zweimal speichern -> alte <stem>.<ts>.sha256 passt zur alten XML, alte meta umbenannt
def test_ensure_meta_bestand_gesendet(tmp_path): XML ohne meta + sent_index-Treffer -> status "gesendet"; zweiter Aufruf liest Datei
def test_ensure_meta_bestand_ohne_audit(tmp_path): -> status "nicht angehängt"
def test_poller_schreibt_meta_und_markiert_gesendet(tmp_path, mocked_db)
def test_poller_attach_fehler_bleibt_archiviert(tmp_path, mocked_db): attach wirft -> meta status "archiviert"
```

Im Archiv-Listing wird `"archiviert"` als „nicht angehängt“ angezeigt (Task 6).

- [ ] **Step 2: Tests laufen lassen** – Expected: FAIL (`ModuleNotFoundError: slim.core_slim.xml_fakten`)
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: Tests** – Expected: PASS, Suite grün
- [ ] **Step 5: Commit** `feat(archiv): Metadaten je XML, Versionen mit eigenem Prüfwert`

### Task 6: Archiv-API für Liste, Suche und Ansicht

**Files:**
- Modify: `slim/api_slim/archive_api.py`
- Create: `slim/core_slim/xml_ansicht.py`
- Test: `tests_slim/test_archive_api.py`, `tests_slim/test_xml_ansicht.py`

**Interfaces:**
- Consumes: `archive_fs.ensure_meta`, `archive_fs.sent_index` (Task 5)
- Produces:
  - `GET /api/archive?q=&von=YYYY-MM-DD&bis=YYYY-MM-DD&limit=` – `q` filtert Rechnungsnummer (Teilstring, ohne Groß/klein) oder Dateiname; `von`/`bis` inklusiv auf `rechnungsdatum`; Einträge zusätzlich mit `rechnung, rechnungsdatum, art, betrag, waehrung, empfaenger, angehaengt_am, status ("gesendet" | "nicht angehängt"), echt (bool|None), version (bool), zuletzt_gesendet (bool), kosit_report (rel_path|None)`; Sortierung neueste Rechnungsdatum zuerst, dann Dateizeit. Bestehende Felder bleiben (Abwärtskompatibilität der Tests). Ungültiges Datum → 422.
  - `zuletzt_gesendet`: je Rechnungsnummer die gesendete Version mit dem jüngsten `angehaengt_am`.
  - `GET /api/archive/ansicht?path=` → `{"fakten": {...}, "verkaeufer": {...}, "kaeufer": {...}, "positionen": [{"nr","bezeichnung","menge","einheit","preis","netto","steuer_prozent"}], "steuern": [{"kategorie","prozent","basis","betrag"}], "summen": {"netto","steuer","brutto","vorauszahlung","zahlbetrag"}, "hinweise": [..], "xml": "<roher Text>"}` – Pfad über das bestehende `_resolve_safe`.
  - `xml_ansicht.lies(xml_bytes) -> dict` (UBL Invoice und CreditNote).

- [ ] **Step 1: Tests**

```python
def test_filter_rechnungsdatum(client): drei XMLs 2026-10-31/11-01/11-30, von=2026-11-01&bis=2026-11-30 -> zwei
def test_filter_datum_ungueltig_422(client)
def test_suche_rechnungsnummer(client)
def test_status_und_zuletzt_gesendet(client): zwei Versionen gesendet + eine archiviert -> genau eine zuletzt_gesendet, archivierte status "nicht angehängt"
def test_echtheit_in_liste(client): manipulierte XML -> echt False
def test_kosit_nur_wenn_vorhanden(client)
def test_ansicht_rechnung(client): positionen, summen.zahlbetrag, xml enthält "<Invoice"
def test_ansicht_pfad_ausserhalb_404(client): path="../../config/connection.json" -> 400/404 wie heute
def test_ansicht_gutschrift()
```

- [ ] **Step 2: Tests laufen lassen** – Expected: FAIL
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: Tests** – Expected: PASS, Suite grün
- [ ] **Step 5: Commit** `feat(archiv): Suche nach Rechnungsdatum, Status, lesbare Ansicht`

### Task 7: Menü, Seiten und Schalter in der Oberfläche

**Files:**
- Create: `slim/frontend/nav.js`, `slim/frontend/archiv.html`
- Modify: `slim/frontend/settings.html`, `slim/frontend/index.html`, `slim/frontend/users.html`, `slim/main_slim.py`
- Test: `tests_slim/test_frontend_pages.py`

**Interfaces:**
- Consumes: `/api/schalter` (Task 1), `/api/settings?page=` (Task 3), `/api/archive*` (Task 6), `/api/trigger-sql` (bestehend), `/api/auth/state` (bestehend, liefert `role`)
- Produces: Routen `/konfiguration`, `/hoteldaten`, `/system` → `settings.html`; `/archiv` → `archiv.html`; `/nav.js` → `nav.js` (`media_type="application/javascript"`); `/settings` → `RedirectResponse("/konfiguration", 307)`.

Vorgaben:
- `nav.js` setzt oben die Menüleiste: Übersicht `/` · Konfiguration XRechnung `/konfiguration` · Hoteldaten `/hoteldaten` · Archiv `/archiv` · System `/system` · Benutzer `/users`; aktiver Punkt hervorgehoben; für Rolle `ansehen` ausgeblendet: Konfiguration, Hoteldaten, System, Benutzer.
- Rechts der Schalter: grün „● XRechnung EIN“, rot „○ XRechnung AUS“, grau „Trigger fehlt“ / „nicht prüfbar“. Klick (nur verwalten) → Bestätigung mit Text: Aus = „Neue Rechnungsmails gehen ohne XRechnung (nur PDF) raus. Bereits wartende Mails bleiben gesperrt, bis wieder eingeschaltet wird.“ / Ein = „Neue Rechnungsmails werden wieder gesperrt und bekommen die XRechnung. Wartende Mails werden jetzt verarbeitet.“ → `POST /api/schalter`. Fehlermeldung (z. B. ORA-01031) sichtbar anzeigen, `grant_sql` mit Kopierknopf zeigen. Bei „Trigger fehlt“ Klick → Dialog mit SQL aus `/api/trigger-sql` und Kopierknopf.
- Zustand alle 30 s neu laden.
- `settings.html`: Seite aus `location.pathname` (`/konfiguration`→xrechnung, `/hoteldaten`→hotel, `/system`→system), Titel = Menüpunkt; Verkäuferdaten-Karte nur auf `hotel`; Neustart-Banner bleibt.
- `index.html`: Archivkasten und Link „Einstellungen“ entfernen, `nav.js` einbinden; Statusfeld „Strategy“ ersetzt durch „XRechnung“ (ein/aus/fehlt/nicht prüfbar) aus `/api/status.trigger`.
- `archiv.html`: Suche (Rechnungsnummer, von, bis), Tabelle wie Spec 3.4, Aktionen Ansehen (Dialog mit lesbarer Rechnung + aufklappbarer Original-XML), XML, Prüfbericht (nur wenn vorhanden); 401 → `/login` wie andere Seiten.
- Alle Seiten: `<script src="/nav.js"></script>`.

- [ ] **Step 1: Tests**

```python
@pytest.mark.parametrize("page", [..., "archiv.html"]) test_seite_vorhanden / test_seite_leitet_bei_401_auf_login
def test_routen_fuer_seiten(): '"/konfiguration"', '"/hoteldaten"', '"/system"', '"/archiv"', '"/nav.js"' in main_slim
def test_settings_leitet_weiter(): TestClient(main_slim.app) GET /settings ohne Folgen -> 307 Location /konfiguration (bzw. Login-Redirect beachten: über Quelltextprüfung)
def test_nav_hat_alle_menuepunkte(): nav.js enthält die sechs Bezeichnungen und "/api/schalter"
def test_nav_texte_schalter(): beide Bestätigungstexte exakt enthalten
def test_alle_seiten_laden_nav(): index, settings, archiv, users enthalten '<script src="/nav.js"></script>'
def test_startseite_ohne_archivkasten(): index.html enthält nicht 'id="archive_table"'
def test_settings_seite_nach_pfad(): settings.html enthält "/konfiguration", "/hoteldaten", "/system" und "?page="
```

- [ ] **Step 2: Tests laufen lassen** – Expected: FAIL
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: Tests** – Expected: PASS, Suite grün
- [ ] **Step 5: Im Browser prüfen** – Dienst lokal starten (Skill `run`), jede Seite öffnen, Schalter-Zustand ohne DB = „nicht prüfbar“, Archiv mit Test-XML in `slim/data/xml/` (danach entfernen)
- [ ] **Step 6: Commit** `feat(ui): Menüleiste, XRechnung-Schalter, Seiten Konfiguration/Hoteldaten/System/Archiv`

### Task 8: Doku

**Files:**
- Modify: `slim/INSTALL.md`, `slim/README.md`

Inhalt: Menüpunkte und was wo steht (Tabelle aus Task 3), Schalter (Verhalten Aus/Ein, gesperrte Mails bleiben gesperrt, Anzeige der vier Zustände, `GRANT ALTER ANY TRIGGER` wenn Trigger einem anderen Benutzer gehört), BT-10-Reihenfolge und Fundort der Freitexte, Archiv (Suche nach Rechnungsdatum, Status, Echtheit). „Verarbeitung“ aus den Tabellen entfernen. `hotel.json`-Tabelle: `bt10_freitext1..4`.

- [ ] **Step 1: Test** `test_doku_nennt_schalter_und_bt10()` in `tests_slim/test_frontend_pages.py`: INSTALL.md enthält „XRechnung EIN“, „GRANT ALTER ANY TRIGGER“, „Bearbeite gewähltes Fenster“; README.md enthält „bt10_freitext1“
- [ ] **Step 2: FAIL** – **Step 3: Doku schreiben** – **Step 4: PASS, Suite grün**
- [ ] **Step 5: Commit** `docs: Menü, Schalter, BT-10-Freitexte, Archiv`
