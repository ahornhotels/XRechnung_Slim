# Schritt 1: Gast in BT-22/BT-70 und Straße 1/2/3 – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Gast steht im Rechnungshinweis (BT-22) und im Lieferempfänger (BT-70), nicht mehr im rechtlichen Käufernamen (BT-44). Die Käuferadresse nutzt Straße 1/2/3 ohne leere Zeilen.

**Architecture:** Positions-SQL und Kopf-SQL liefern neue Rohspalten. Dazu gehören die Herkunft je Buchung über `ZPOS_ORIGINATED_*` und alle drei Straßenzeilen. Ein neues Modul `modules/invoice_enrich.py` wertet sie aus, rein und ohne DB. `fetch_invoice` ruft es auf, bevor der Validator läuft. Die Templates für Rechnung und Gutschrift geben nur noch aus, was im Kopf steht. Fehlen die ORIGINATED-Spalten in einer Suite8-Version, läuft die Positions-SQL ohne sie weiter. Das ist derselbe Mechanismus wie heute bei der Anzahlungsspalte, nur verallgemeinert.

**Tech Stack:** Python 3.12, Oracle-SQL (Suite8), Jinja2-Templates (UBL 2.1 / XRechnung 3.0), pytest, lxml (XSD), lokaler KoSIT-Validator.

**Spec:** `docs/superpowers/specs/2026-11-06-slim-umbau-design.md`, Abschnitte 3, 4, 5, 6. Schritt 4 (Zusammenfassen, Positionstexte) ist **nicht** Teil dieses Plans.

## Global Constraints

- Öffentliches Repo: keine Hausnamen, echten Rechnungsnummern, Gastnamen oder Zugangsdaten in Code, Tests, Commits. Testdaten erfunden („Erika Muster“, „Zi. 101“).
- Suite8: nur SELECT. Keine neuen Schreibzugriffe in diesem Schritt.
- Neue SQL-Spalten brauchen Marker in `_EXPECTED_OVERRIDE_MARKERS` (`modules/invoice_fetcher.py`). Eine fehlende Spalte (ORA-00904) führt zum Rückfall, nicht zum Scheitern aller Rechnungen.
- Testbefehl: `C:\FIDELIO\Suite8XRechnung\.venv\Scripts\python.exe -m pytest tests_slim -q`. Ausgangsstand 287 passed, 1 skipped. Am Ende muss alles grün sein.
- KoSIT: `modules.kosit_validator.validate(xml)`. Erlaubt sind nur PEPPOL-EN16931-R020/R010 und BR-DE-6/7 (Stammdaten synthetischer Rechnungen).
- Kein „None“ und keine leeren Elemente in der XML. None wird zu leer, leere Elemente werden nicht geschrieben.
- Gastzeilen-Vorlage, Standard exakt: `Gast: {gast}, Zimmer {zimmer}, {anreise} bis {abreise}`. Datumsformat `TT.MM.JJJJ`. Trenner zu einem vorhandenen Hinweis: ` · ` (Leerzeichen, Mittelpunkt U+00B7, Leerzeichen).
- Arbeitszweig `feature/slim-umbau`. Commits mit den Attribution-Zeilen aus der Session. Kein Release in diesem Plan.

## Review Focus

1. **Name mit `&` oder `<`** (z. B. „Müller & Söhne“) in Gast oder Freitext → die XML bleibt wohlgeformt und XSD-gültig (Test in Task 4).
2. **Zeile 1 leer, Zeile 2 gefüllt**, oder Zeilen nur aus Leerzeichen → Zeile 2 wird zur Straße, und es entsteht kein leeres `AdditionalStreetName` (Test in Task 1).
3. **Rechnung auf ein Finanzkonto**, alle Buchungen ohne Herkunftsreservierung → keine Gastzeile, kein BT-70, und es entsteht kein „Gast: “ (Test in Task 3).
4. **Ältere Suite8-Version ohne `ZPOS_ORIGINATED_*`** → Positionen laden ohne Herkunft, die Rechnung geht wie bisher hinaus. Die Anzahlungserkennung bleibt intakt (Test in Task 2).
5. **Gutschrift bzw. VOID-Storno** → dieselbe Adress- und Gastlogik wie bei der Rechnung, das CreditNote-XSD bleibt gültig (Test in Task 4).

---

### Task 1: Straße 1/2/3

**Files:**
- Modify: `sql/invoice_header.sql`: neue Spalten nach `CustomerStreetName` (Zeile 86)
- Create: `modules/invoice_enrich.py`
- Modify: `modules/invoice_fetcher.py`: Marker `invoice_header.sql` und Aufruf in `fetch_invoice` (nach den Totals, vor `is_credit_note`)
- Modify: `templates/xrechnung_3.0.xml.j2` (Käufer-`PostalAddress`, Zeilen 71–76), `templates/creditnote_3.0.xml.j2` (Zeilen 71–76)
- Test: `tests_slim/test_invoice_enrich_address.py`

**Interfaces:**
- Produces: `invoice_enrich.street_lines(*raw: str | None) -> list[str]` sowie `invoice_enrich.apply_customer_address(header: dict) -> None`. Die zweite Funktion setzt `header["customerstreetname"]`, `header["customeradditionalstreetname"]` und `header["customeraddressline"]`, jeweils `str` oder `None`.
- SQL liefert, kleingeschrieben im Dict: `customeradrstreet1/2/3` aus `xadr_id = zinv_xadr_id` sowie `customerprimstreet1/2/3` aus der Primäradresse (`min(xadr_id)` mit `xadr_primary=1`, Unterabfrage wie in Zeile 86).

- [ ] **Step 1: Failing tests schreiben**

```python
from modules import invoice_enrich as ie

def test_leere_zeilen_ruecken_nach_oben():
    assert ie.street_lines(None, "Hinterhaus", "  ") == ["Hinterhaus"]
    assert ie.street_lines("", "Postfach 1", "Etage 3") == ["Postfach 1", "Etage 3"]

def test_drei_zeilen_auf_bt50_51_163():
    h = {"customeradrstreet1": "Kundenweg 2", "customeradrstreet2": "Haus B",
         "customeradrstreet3": "c/o Einkauf", "customerstreetname": "Kundenweg 2"}
    ie.apply_customer_address(h)
    assert (h["customerstreetname"], h["customeradditionalstreetname"],
            h["customeraddressline"]) == ("Kundenweg 2", "Haus B", "c/o Einkauf")

def test_rechnungsadresse_leer_nimmt_primaeradresse():
    h = {"customeradrstreet1": None, "customeradrstreet2": None, "customeradrstreet3": None,
         "customerprimstreet1": None, "customerprimstreet2": "Am Markt 5",
         "customerprimstreet3": None, "customerstreetname": None}
    ie.apply_customer_address(h)
    assert h["customerstreetname"] == "Am Markt 5" and h["customeradditionalstreetname"] is None

def test_ohne_neue_spalten_bleibt_alles_wie_bisher():  # SQL-Override ohne Marker
    h = {"customerstreetname": "Kundenweg 2"}
    ie.apply_customer_address(h)
    assert h["customerstreetname"] == "Kundenweg 2"
    assert h.get("customeradditionalstreetname") is None

def test_xml_adresse_reihenfolge_und_keine_leeren_elemente():
    # _base_invoice aus test_creditnote_xsd, role 0 und 3
    # Rechnung mit customeradditionalstreetname="Haus B" und customeraddressline=None:
    #   AccountingCustomerParty/PostalAddress enthält StreetName, AdditionalStreetName,
    #   kein cac:AddressLine.
    # Mit customeraddressline="c/o Einkauf" steht cac:AddressLine/cbc:Line nach
    #   PostalZone und vor Country.
    # XSD gültig (_assert_xsd_valid, beide Schemata).
    ...
```

Den letzten Test mit lxml-XPath ausschreiben. Er läuft für Rechnung (role 0) und Gutschrift (role 3).

- [ ] **Step 2: Tests laufen lassen, FAIL erwartet** (`ModuleNotFoundError: modules.invoice_enrich`)

Run: `...python.exe -m pytest tests_slim/test_invoice_enrich_address.py -v`

- [ ] **Step 3: Umsetzen**
  - **SQL:** sechs Spalten `CustomerAdrStreet1..3` und `CustomerPrimStreet1..3`. `CustomerStreetName` bleibt unverändert, als Rückfall für alte Overrides.
  - **Marker:** `"CustomerAdrStreet2"` in `_EXPECTED_OVERRIDE_MARKERS["invoice_header.sql"]` ergänzen.
  - **`apply_customer_address`:**
    - Ist keiner der sechs Schlüssel im Dict, ändert die Funktion nichts.
    - Sonst nimmt sie `street_lines(adr1..3)`. Ist das Ergebnis leer, nimmt sie `street_lines(prim1..3)`.
    - Die Zeilen 1 bis 3 gehen in die drei Felder. Fehlende Felder werden `None`.
    - Ist beides leer, bleibt `customerstreetname` unverändert, dann greift der Validator wie heute.
  - **Templates:** `AdditionalStreetName` direkt nach `StreetName`. `cac:AddressLine` nach `PostalZone`, vor `cac:Country`. Beide nur mit `{% if %}` und `|e`.

- [ ] **Step 4: Tests grün, Gesamtsuite grün**

- [ ] **Step 5: Commit** `feat(xml): Käuferadresse aus Straße 1/2/3, leere Zeilen überspringen`

---

### Task 2: Herkunft je Buchung (ORIGINATED) in der Positions-SQL

**Files:**
- Modify: `sql/invoice_lines.sql`: innerer und äußerer SELECT, neben den `Deposit*`-Spalten
- Modify: `modules/invoice_fetcher.py:110-136`: Rückfall verallgemeinern
- Modify: `tests_slim/test_deposit_allowances.py:255-290`: Monkeypatch auf den neuen Zustand umstellen
- Test: `tests_slim/test_origin_columns.py`

**Interfaces:**
- Produces: neue Schlüssel je Position (kleingeschrieben):

| Schlüssel | Typ | Inhalt |
|---|---|---|
| `originyresid` | int oder None | `nvl(z.zpos_originated_yres_id, z.zpos_yres_id)` |
| `originxcmsid` | int oder None | `z.zpos_originated_xcms_id`, sonst `YRES_XCMS_ID` der Herkunftsreservierung |
| `originguestname` | str oder None | `v8_rep_name.NAME2` zu `originxcmsid`, dieselbe Namensform wie `GUESTNAME` in `invoice_tax.sql` |
| `originroom` | str oder None | Zimmer am Buchungstag mit Fallback, SQL exakt aus Spec Abschnitt 6, mit `nvl(z.zpos_originated_yres_id, z.zpos_yres_id)` statt `p.zpos_originated_yres_id` |
| `originarrival`, `origindeparture` | `'YYYY-MM-DD'` oder None | `TRUNC(YRES_EXPARRTIME)` bzw. `TRUNC(YRES_EXPDEPTIME)` der Herkunftsreservierung |

- Produces: `invoice_fetcher._OPTIONAL_LINE_COLUMNS: tuple[str, ...] = ("ZPOS_DEPOSIT_ZINV_ID", "ZPOS_ORIGINATED_YRES_ID", "ZPOS_ORIGINATED_XCMS_ID")` und `invoice_fetcher._missing_line_columns: set[str]`. Ersetzt `_deposit_column_missing`.
- Produces: `invoice_fetcher._lines_sql_without(sql: str, columns: set[str]) -> str`. Ersetzt `z.<spalte>` durch `to_number(null)`, ohne Rücksicht auf Groß- und Kleinschreibung.

- [ ] **Step 1: Failing tests schreiben**

```python
def test_lines_sql_liefert_herkunftsspalten():
    sql = (SQL_DIR / "invoice_lines.sql").read_text(encoding="utf-8")
    for col in ("OriginYresId", "OriginXcmsId", "OriginGuestName", "OriginRoom",
                "OriginArrival", "OriginDeparture"):
        assert col in sql
    assert "zpos_originated_yres_id" in sql.lower()
    assert "OriginYresId" in _EXPECTED_OVERRIDE_MARKERS["invoice_lines.sql"]

def test_fehlende_originated_spalte_faellt_zurueck(monkeypatch):
    # Cursor wirft beim 1. execute ORA-00904 "Z"."ZPOS_ORIGINATED_YRES_ID",
    # beim 2. (SQL ohne diese Spalte) liefert er eine Zeile.
    # Erwartet: Zeile geladen, "ZPOS_ORIGINATED_YRES_ID" in _missing_line_columns,
    # im 2. SQL kommt "z.zpos_originated_yres_id" nicht mehr vor, z.zpos_deposit_zinv_id aber schon.

def test_zwei_fehlende_spalten_nacheinander(monkeypatch):
    # 1. execute: Fehler DEPOSIT, 2.: Fehler ORIGINATED_XCMS, 3.: ok -> 3 Aufrufe, Zeile geladen.

def test_andere_db_fehler_werden_nicht_geschluckt(monkeypatch):
    # ORA-00942 -> Exception propagiert.
```

- [ ] **Step 2: FAIL erwartet** (Spalten fehlen, `_missing_line_columns` unbekannt)

- [ ] **Step 3: Umsetzen**
  - **SQL:** Spalten ergänzen, Marker `"OriginYresId"` hinzufügen.
  - **`_fetch_lines`:** Schleife über höchstens `len(_OPTIONAL_LINE_COLUMNS)+1` Versuche.
    - Enthält die Fehlermeldung eine noch nicht als fehlend markierte optionale Spalte, wird diese markiert. Dann folgt eine Warnung pro Spalte und Prozess, und das SQL wird ohne sie wiederholt.
    - Jeder andere Fehler wird weitergereicht.
  - **Bestehende Deposit-Fallback-Tests:** Sie patchen künftig `_missing_line_columns` mit `set()` statt `_deposit_column_missing`. Die Assertions bleiben unverändert.

- [ ] **Step 4: Tests grün, Gesamtsuite grün**

- [ ] **Step 5: Commit** `feat(sql): Herkunft je Buchung (ORIGINATED) mit Rückfall für ältere Suite8`

---

### Task 3: Gästeermittlung und Gastzeile

**Files:**
- Modify: `modules/invoice_enrich.py`
- Modify: `slim/config/hotel.json.example`: Schlüssel `"gastzeile"` mit dem Standardtext
- Modify: `modules/invoice_fetcher.py`: `_gastzeile_template()` sowie Aufruf in `fetch_invoice` direkt nach `apply_customer_address`
- Test: `tests_slim/test_invoice_enrich_guest.py`

**Interfaces:**
- Consumes: Positionsschlüssel aus Task 2. `invoice_fetcher.is_deposit_line(line) -> bool`.
- Produces:
  - `invoice_enrich.GASTZEILE_STANDARD: str = "Gast: {gast}, Zimmer {zimmer}, {anreise} bis {abreise}"`
  - `invoice_enrich.guests(lines: list[dict]) -> list[dict]`: je eindeutigem `(originyresid, originxcmsid)` ein Dict `{"gast", "zimmer", "anreise", "abreise"}`, Datum als `TT.MM.JJJJ`. Es zählen nur Positionen mit `originyresid`, ohne Anzahlungszeilen. Reihenfolge wie erstes Auftreten. Das `zimmer` ist das der ersten Position dieses Gastes.
  - `invoice_enrich.guest_line(template: str, guest: dict) -> str | None`
  - `invoice_enrich.apply_guest_info(invoice: dict, template: str) -> None`. Setzt `header["note"]` und `header["deliverypartyname"]`.
  - `invoice_fetcher._gastzeile_template() -> str`: liest `hotel.json["gastzeile"]` und fällt auf `GASTZEILE_STANDARD` zurück, wenn der Schlüssel fehlt. Ein **leerer String** bleibt leer und bedeutet „aus“.

**Regel für `guest_line`, ein Algorithmus, den die Tests allein nicht festlegen:**

```python
# Vorlage an ", " in Segmente teilen. Ein Segment entfällt, wenn einer seiner
# Platzhalter leer ist. Ist {gast} leer oder die Vorlage leer -> None.
# Verbleibende Segmente formatieren und mit ", " verbinden.
```

- [ ] **Step 1: Failing tests schreiben**

```python
G = {"gast": "Erika Muster", "zimmer": "101", "anreise": "02.03.2026", "abreise": "05.03.2026"}

def test_gastzeile_standard():
    assert ie.guest_line(ie.GASTZEILE_STANDARD, G) == \
        "Gast: Erika Muster, Zimmer 101, 02.03.2026 bis 05.03.2026"

def test_fehlendes_zimmer_nur_dieser_teil_entfaellt():
    assert ie.guest_line(ie.GASTZEILE_STANDARD, {**G, "zimmer": None}) == \
        "Gast: Erika Muster, 02.03.2026 bis 05.03.2026"

def test_ohne_gast_oder_leere_vorlage_keine_zeile():
    assert ie.guest_line(ie.GASTZEILE_STANDARD, {**G, "gast": None}) is None
    assert ie.guest_line("", G) is None

def test_ein_gast_setzt_note_und_bt70():
    # 2 Leistungszeilen derselben Herkunft (yres 11, xcms 21) + 1 Anzahlungszeile
    # header["note"] = None -> note == Gastzeile, deliverypartyname == "Erika Muster"

def test_vorhandener_hinweis_wird_angehaengt():
    # header["note"] = "Tagung Vertrieb" -> "Tagung Vertrieb · Gast: Erika Muster, ..."

def test_mehrere_gaeste_keine_kopfzeile():
    # Herkünfte (11,21) und (12,22) -> note unverändert, deliverypartyname None

def test_mitreisender_eigenes_profil_zaehlt_als_zweiter_gast():
    # gleiche yres 11, xcms 21 und 23 -> len(guests) == 2 -> keine Kopfzeile

def test_nur_kontobuchungen_ohne_herkunft():
    # alle originyresid None -> guests == [], note unverändert, kein "Gast:" irgendwo

def test_kontobuchung_neben_einem_gast_zaehlt_nicht():
    # (11,21) + Zeile mit originyresid None -> genau ein Gast -> Kopfzeile gesetzt

def test_gastzeile_vorlage_aus_hotel_json(monkeypatch, tmp_path):
    # hotel.json ohne Schlüssel -> GASTZEILE_STANDARD; mit "" -> ""; mit "Gast: {gast}" -> so
```

- [ ] **Step 2: FAIL erwartet**

- [ ] **Step 3: Umsetzen**
  - **`apply_guest_info`:** Bei genau einem Gast und einer Zeile ungleich None wird `note` gesetzt. Ist `note` schon gefüllt, wird mit ` · ` angehängt. `deliverypartyname` erhält den Gastnamen.
  - **Sonst:** `deliverypartyname = None`, `note` bleibt unverändert.
  - **Datumsformat:** `xml_builder._de_date` wiederverwenden (zirkulären Import vermeiden, also die Funktion nach `invoice_enrich` verschieben und in `xml_builder` importieren).

- [ ] **Step 4: Tests grün, Gesamtsuite grün**

- [ ] **Step 5: Commit** `feat(xml): Gastzeile in BT-22 nach Vorlage, nur bei genau einem Gast`

---

### Task 4: Templates – BT-44 Rechnungsempfänger, BT-70 Lieferempfänger

**Files:**
- Modify: `templates/xrechnung_3.0.xml.j2`
  - Zeile 78: `RegistrationName` nur noch `header.customername`
  - neuer `cac:Delivery`-Block nach `</cac:AccountingCustomerParty>` und vor `cac:PaymentMeans`
- Modify: `templates/creditnote_3.0.xml.j2`: dieselben Stellen
- Test: `tests_slim/test_guest_xml.py`

**Interfaces:**
- Consumes: `header["deliverypartyname"]` und `header["note"]` aus Task 3.

- [ ] **Step 1: Failing tests schreiben**

```python
def test_bt44_ist_rechnungsempfaenger_nicht_gast():
    # _base_invoice(0, customername="Kunde AG", customerregistrationname="Erika Muster")
    # -> AccountingCustomerParty/.../PartyLegalEntity/RegistrationName == "Kunde AG"

def test_bt70_und_bt22_bei_einem_gast():
    # header note="Gast: Erika Muster, Zimmer 101, ...", deliverypartyname="Erika Muster"
    # -> cbc:Note (Kopf) == note; cac:Delivery/cac:DeliveryParty/cac:PartyName/cbc:Name == "Erika Muster"

def test_ohne_gast_kein_delivery_element():
    # deliverypartyname None -> kein cac:Delivery

def test_sonderzeichen_bleiben_wohlgeformt():
    # deliverypartyname="Müller & Söhne <GmbH>", note mit "&" -> etree.fromstring ok,
    # Text exakt erhalten, XSD gültig

def test_gutschrift_gleich():
    # role 3, gleiche Werte -> RegistrationName "Kunde AG", Delivery vorhanden, CreditNote-XSD gültig
```

- [ ] **Step 2: FAIL erwartet** (RegistrationName ist „Erika Muster“, `Delivery` fehlt)

- [ ] **Step 3: Templates anpassen**
  - Der Block lautet `{% if header.deliverypartyname %}<cac:Delivery><cac:DeliveryParty><cac:PartyName><cbc:Name>{{ header.deliverypartyname|e }}</cbc:Name></cac:PartyName></cac:DeliveryParty></cac:Delivery>{% endif %}`.
  - `customerregistrationname` bleibt im SQL. Die Templates lesen es nicht mehr.

- [ ] **Step 4: Tests grün, Gesamtsuite grün**

- [ ] **Step 5: KoSIT-Gegenprobe**
  - Ein Skript im Scratchpad rendert vier synthetische Rechnungen: ein Gast mit drei Adresszeilen, mehrere Gäste, Finanzkonto ohne Herkunft und eine Gutschrift mit Gast.
  - Jede geht durch `kosit_validator.validate`.
  - Erwartet: keine Befunde außer PEPPOL-EN16931-R020/R010 und BR-DE-6/7.

- [ ] **Step 6: Commit** `feat(xml): BT-44 nur Rechnungsempfänger, Gast zusätzlich in BT-70`

---

### Task 5: Abschluss Schritt 1

- [ ] **Step 1:** Gesamtsuite. Erwartet: 287 + neue Tests passed, 1 skipped, keine Warnung.
- [ ] **Step 2:** `git diff master...feature/slim-umbau` nach Hausnamen, echten Nummern und Tokens durchsuchen. Erwartet: keine Treffer.
- [ ] **Step 3:** In der `STATUS.md` (gitignored) den Stand von Schritt 1 eintragen. Dazu gehört der Hinweis, dass die ORIGINATED-Spalten nur in einem Haus bestätigt sind und der Rückfall greift.
- [ ] **Step 4:** Dem Nutzer berichten. Release erst nach dem Merge und nach seiner Freigabe.
