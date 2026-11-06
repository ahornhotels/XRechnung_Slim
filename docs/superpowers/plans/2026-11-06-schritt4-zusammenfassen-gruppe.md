# Schritt 4: Positionen zusammenfassen, Gruppenrechnung je Gast und Zimmer – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Gleiche Buchungen werden zu einer Position mit echter Menge zusammengefasst („Logis 3 × 100,00“). Auf Rechnungen mit mehreren Gästen trägt jede Position „Zi. 101 · Erika Muster“ und ihren eigenen Leistungszeitraum.

**Architecture:**
- **SQL:** `invoice_lines.sql` liefert je Buchung zusätzlich Menge, Brutto-Einzelpreis und Buchungsdatum.
- **Zusammenfassen:** Eine reine Funktion `invoice_enrich.group_lines()` fasst nach dem Fetch zusammen. Die Reihenfolge in `fetch_invoice` ist: Fetch → Auslagen-Freigabe → Zusammenfassen → Gastinfo.
- **Kennzeichnung:** Sie setzt pro Position `note` (BT-127) und `periodstart`/`periodend` (BT-134/135). Den Rechnungszeitraum (BT-73/74) erweitert sie so, dass alle Positionen hineinpassen.
- **Templates:** Sie geben die Positionshinweise und Positionszeiträume aus. Den Preis schreiben sie mit bis zu 4 Nachkommastellen.
- **Steuer:** Damit beim Neuberechnen der Steuer (Pfad mit Abschlägen) keine neue Rundungsdifferenz entsteht, trägt jede zusammengefasste Position `vatparts`, die Summe der je Buchung gerundeten Steuer. `_split_negative_lines_to_allowances` verwendet diesen Wert.

**Spec:** `docs/superpowers/specs/2026-11-06-slim-umbau-design.md`, Abschnitt 9, mit den Nutzervorgaben:
- auch bei einem Gast zusammenfassen,
- Korrekturen und Stornos nicht verrechnen,
- Gast im Schlüssel.

## Global Constraints

- **Schlüssel:**
  - Herkunftsreservierung `originyresid`
  - Gast `originxcmsid`
  - Zimmer `originroom`
  - `itemcode` und `itemname`
  - Brutto-Einzelpreis `grossunitprice`
  - Kategorie
  - Satz
  - **Vorzeichen** des Betrags
- **Werte der Position:**
  - Menge = Summe `quantity`.
  - Netto = Summe `lineextensionamountnet`, brutto entsprechend.
  - Netto-Einzelpreis = Netto / Menge, auf 4 Nachkommastellen, so dass `round(Menge × Preis, 2) == Netto` gilt (PEPPOL-EN16931-R120). Gelingt das nicht exakt, gilt Menge 1 und Preis = Netto.
  - Ist die Menge ≤ 0 oder fehlt sie, bleibt die Menge 1 und der Preis = Netto.
- **Ausgenommen vom Zusammenfassen:** Anzahlungszeilen (`is_deposit_line`) bleiben unangetastet und einzeln.
- **Gruppenrechnung:** Mehr als ein Gast heißt mehr als ein Eintrag in `invoice_enrich.guests(lines)`. Nur dann gibt es Positionstexte im Format `Zi. {zimmer} · {gast}`.
  - Fehlt das Zimmer, ist der Text nur `{gast}`. Fehlt der Gast, gibt es keinen Text.
  - Bei einer Konto-Buchung ohne Herkunft gibt es keinen Text.
- **Sortierung:** Die Reihenfolge der Positionen ändert sich nur bei Gruppenrechnungen:
  1. Zimmer numerisch (9 vor 10)
  2. nicht numerische Zimmer danach
  3. ohne Zimmer zuletzt
  4. dann Gast, dann Leistung, dann erstes Buchungsdatum
- **Ohne Gruppenrechnung** bleibt die Reihenfolge der ersten Buchung.
- **Abschläge (negative Positionen):** Bei einer Gruppenrechnung lautet der Grund (BT-97) `{itemname} · Zi. {zimmer} · {gast}`.
- **Konfiguration:** `hotel.json` → `positionen_zusammenfassen`, Standard `true`. Mit `false` bleibt jede Buchung eine Position. Menge, Preis, Positionstexte und Zeitraum gelten trotzdem.
- **Override-Marker:** `invoice_lines.sql` bekommt den Marker `GrossUnitPrice`. Fehlen die Spalten (alter Override), wird nicht zusammengefasst, die Menge bleibt 1 und Slim warnt einmal.
- Tests wie bisher. Nach jeder Aufgabe `/code-review high`. KoSIT-Gegenproben für PEPPOL-R110/R111/R120 und BR-CO-10.

## Review Focus

1. **Drei Nächte zu 100 €, eine Nacht zu 120 €:** zwei Positionen (3 × 100 und 1 × 120) mit korrekten Zeiträumen (Task 2).
2. **Logis 3 × 33,34 € brutto bei 7 %:** Preis mit 4 Nachkommastellen, R120 grün, Summe gleich der Summe der Einzelbuchungen (Task 2 und Task 3, KoSIT).
3. **Gruppe mit Rabatt pro Gast:** Der Abschlagsgrund nennt Zimmer und Gast, und die Steuer der Abschläge ist gleich der Steuer vor dem Zusammenfassen (Task 2 und Task 3).
4. **Gruppe mit verschiedenen Anreisetagen:** Der Rechnungszeitraum umfasst alle Positionen, R110/R111 sind grün (Task 3).
5. **Storno einer Buchung (+100 / −100):** Beide bleiben sichtbar, als Position und als Abschlag (Task 2).

---

### Task 1: SQL-Spalten Menge, Einzelpreis, Buchungsdatum

**Files:** `sql/invoice_lines.sql`, `modules/invoice_fetcher.py` (Marker), Test `tests_slim/test_group_lines.py`

- Im inneren SELECT:
  - `z.zpos_quantity*decode(z.zpos_cdt,5,-1,1) Quantity`
  - `round(z.zpos_grossunitprice,4) GrossUnitPrice`
  - `to_char(trunc(z.zpos_postdate),'YYYY-MM-DD') PostDate`
- Im äußeren SELECT werden die drei Spalten unverändert durchgereicht.
- `InvoicedQuantity` bleibt 1. Das neue Feld heißt `quantity`.
- Test: Die Spalten und der Marker sind vorhanden.

### Task 2: `invoice_enrich.group_lines(lines: list[dict], merge: bool) -> list[dict]` und `extend_invoice_period(header, lines) -> None`

**Files:** `modules/invoice_enrich.py`, `modules/invoice_fetcher.py` (Aufruf, `_positionen_zusammenfassen()`), `slim/config/hotel.json.example`, `modules/xml_builder.py` (`vatparts` in `_split_negative_lines_to_allowances` für Positionen und Abschläge, `guestlabel` im Abschlagsgrund), Test `tests_slim/test_group_lines.py`

Gesetzte Felder je Ergebnisposition:
- `invoicedquantity`: Text, ohne überflüssige Nullen, z. B. `"3"`, `"0.5"`
- `priceamount`: Text, bis 4 Nachkommastellen
- `lineextensionamountnet` und `lineextensionamount`: Summen als Text mit 2 Nachkommastellen
- `vatparts`: Summe von `round(net_i × pct / 100, 2)` als Text
- `periodstart` und `periodend`: frühestes und spätestes `postdate`
- `note`: nur bei einer Gruppenrechnung
- `guestlabel`: nur bei einer Gruppenrechnung, `Zi. 101 · Erika Muster`

Tests:
- `test_gleiche_buchungen_eine_position`: 3 × Logis 107/100 → Menge 3, Preis 33.3333, Netto 300.00, R120-Gleichung erfüllt
- `test_anderer_preis_eigene_position`
- `test_storno_nicht_verrechnet`: +100 und −100 → zwei Positionen
- `test_anzahlung_bleibt_unangetastet`
- `test_menge_null_oder_fehlend_menge_eins`
- `test_ein_gast_kein_positionstext`
- `test_gruppe_positionstext_und_sortierung`: Zimmer 10, 9 und ohne Zimmer, mit Namen
- `test_konto_buchung_ohne_text`
- `test_zusammenfassen_aus_nur_menge_und_zeitraum`
- `test_rechnungszeitraum_wird_erweitert`: Kopf 02.–05.03., Position 01.03. → Start 01.03. Ohne Kopfzeitraum werden Min und Max der Positionen gesetzt.
- `test_vatparts_erhaelt_steuer_bei_abschlaegen`: Rechnung mit Abschlag, die Steuer in BG-23 ist identisch mit der Fassung ohne Zusammenfassen
- `test_abschlagsgrund_nennt_gast_in_gruppe`

### Task 3: Templates

**Files:** `templates/xrechnung_3.0.xml.j2` und `templates/creditnote_3.0.xml.j2` (InvoiceLine/CreditNoteLine), `modules/xml_builder.py` (Filter `price4`), Test `tests_slim/test_group_lines_xml.py`

- UBL-Reihenfolge in der Position: `ID`, `Note`, Menge, `LineExtensionAmount`, `InvoicePeriod` (Start, Ende), `Item`, `Price`.
- `Note` nur, wenn gesetzt. `InvoicePeriod` nur, wenn beide Daten gesetzt sind.
- `PriceAmount` über einen neuen Filter `price4`: 2 bis 4 Nachkommastellen, nachlaufende Nullen nach der 2. Stelle entfernt.
- Tests: Reihenfolge und XSD für Rechnung und Gutschrift. KoSIT-Gegenproben für Gruppe mit Rabatt, verschiedene Anreisetage und 3 × 33,34.

### Task 4: Abschluss

Gesamtsuite, Durchsicht auf echte Daten, STATUS.md, Bericht. Danach bittet Slim TestZ um einen Lesetest der SQL-Spalten in einem Haus.
