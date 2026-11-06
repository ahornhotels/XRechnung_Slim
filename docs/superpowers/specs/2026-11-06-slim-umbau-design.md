# Slim-Umbau: Gast, Gruppenrechnung, Adresse, Nur-XML, Auslagen, Oberfläche

Stand: 06.11.2026 · Ausgangsversion v1.10.9 · Vorbild: OPERA-V5-XRechnung

## 1. Absicht

XRechnung_Slim erzeugt aus Suite8-Rechnungen XRechnungen (UBL, KoSIT-geprüft) und hängt
sie an die von Suite8 vorbereitete Rechnungsmail. Der Umbau verfolgt zwei Ziele:

- **Fachlich richtigere XRechnungen:**
  - Der Gast steht nicht mehr im Käuferfeld.
  - Gruppenrechnungen zeigen Gast und Zimmer je Position.
  - Adressen gehen nicht mehr verloren.
  - Auslagen werden korrekt verrechnet.
- **Betrieb ohne Dateibearbeitung:** Jede Einstellung ist in der Weboberfläche änderbar,
  geschützt durch eine Anmeldung.

Vorbild ist die Schwester-Anwendung OPERA-V5-XRechnung (Repo
`ahornhotels/OPERA-V5-XRechnung`), die diese Punkte bereits löst. Wo dieses Dokument
„wie OPERA“ sagt, gilt das dortige Verhalten. Die Pfade sind unten jeweils genannt.

## 2. Ziele, Nicht-Ziele, Anti-Ziele

**Ziele** in der vom Nutzer festgelegten Reihenfolge, je Schritt ein eigenes Release:

1. Gast nach BT-22 und BT-70 sowie Straße 1/2/3
2. Auslagen prüfen und bei Bedarf korrigieren
3. Nur-XML-Versand über das Membership „PDF“
4. Positionen zusammenfassen sowie Gruppenrechnung je Gast und Zimmer
5. Oberfläche: Anmeldung und vollständige Konfiguration

Schritt 1 nutzt für die Gastzeile bereits die Herkunftsfelder aus Abschnitt 6. Die
Konfigurationswerte für die Schritte 1 bis 4 kommen zunächst in die vorhandenen
JSON-Dateien und werden in Schritt 5 in der Oberfläche sichtbar.

**Nicht-Ziele**
- Kein Wechsel des Frameworks. Slim bleibt bei FastAPI mit statischem Frontend
  (`slim/frontend/*.html` und `fetch`). Die Jinja-Serverseiten von OPERA werden nicht
  übernommen.
- Kein Umzug der Konfigurationsdateien. `slim/config/*.json` bleibt an seinem Ort und
  in seinem Format, damit bestehende Installationen und der Auto-Updater weiterlaufen.
- Keine Positionsart „jede Buchung einzeln“ als Umschalter pro Rechnung. Das könnte
  später kommen.
- Keine Änderung am Anzahlungsmuster aus v1.10.9.

**Anti-Ziele.** Das Ergebnis wäre gescheitert, auch wenn es technisch läuft, wenn …
- Slim in Suite8 etwas anderes löscht als die PDF-Verknüpfung einer noch nicht
  versendeten Mail.
- eine Gruppenrechnung an einer Position den Namen eines fremden Gastes zeigt.
- „None“, ein leeres „Gast: “ oder eine leere Adresszeile in der XML steht.
- ein Update eine bestehende Konfiguration überschreibt oder unlesbar macht.
- die Oberfläche das Datenbankpasswort oder Tokens im Klartext anzeigt oder protokolliert.

## 3. Rahmenbedingungen

- **Öffentliches Repo:** keine Hausnamen, keine echten Rechnungsnummern, keine Gastnamen
  und keine Zugangsdaten in Code, Tests, Doku oder Release-Notes. Testdaten sind
  erfunden.
- **Suite8-Zugriff:** Slim liest und hängt bisher nur an. Neu ist genau ein Löschvorgang
  (Schritt 3). Sonst gibt es keine schreibenden Zugriffe.
- **SQL-Overrides:** Unter `slim/data/sql_overrides/` können Häuser eigene SQL-Fassungen
  haben. Neue Spalten brauchen Marker in `_EXPECTED_OVERRIDE_MARKERS`
  (`modules/invoice_fetcher.py`). Fehlt eine Spalte in einer Suite8-Version, muss Slim wie
  bei `ZPOS_DEPOSIT_ZINV_ID` auf das bisherige Verhalten zurückfallen, statt alle
  Rechnungen scheitern zu lassen.
- **Gesichert sind die Suite8-Strukturen nur für ein Haus.** Spalten, die neu genutzt
  werden, brauchen denselben Rückfall.
- **Prüfung:** Jede XML-Änderung wird mit dem lokalen KoSIT-Validator geprüft
  (`modules/kosit_validator.py`). Erlaubt sind nur die bekannten Stammdatenbefunde
  synthetischer Testrechnungen (PEPPOL-EN16931-R020/R010, BR-DE-6/7).
- **Tests:**
  `C:\FIDELIO\Suite8XRechnung\.venv\Scripts\python.exe -m pytest tests_slim -q`, Stand
  v1.10.9: 287 grün. Es wird testgetrieben gearbeitet.
- **Release:** VERSION erhöhen, Commit, kommentierter Tag, Push, GitHub-Release, dann
  `releases/latest` prüfen. Der Auto-Updater orientiert sich an den Tags.

## 4. Schritt 1a – Gast in BT-22 und BT-70, raus aus BT-44

**Heute:**
- `sql/invoice_header.sql` liefert `CustomerRegistrationName` (Gast der Reservierung
  bzw. des Kontos). Das Template schreibt ihn in `PartyLegalEntity/RegistrationName`, also
  BT-44, den rechtlichen Käufernamen. Ist das Feld leer, nimmt Slim `CustomerName`.
- `BuyerReference` (BT-10) fällt ohne `DXR`-Membership auf den Namen des
  Rechnungsempfängers zurück. Das bleibt unverändert.

**Neu:**
- **BT-44:** Es steht immer der Rechnungsempfänger (`CustomerName`). Der Gast wird
  dort nicht mehr verwendet.
- **BT-22, Rechnung mit genau einem Gast:** Kopfhinweis nach der Vorlage
  `"Gast: {gast}, Zimmer {zimmer}, {anreise} bis {abreise}"`.
  - Datumsformat TT.MM.JJJJ.
  - Gibt es bereits einen Hinweis (heute `zwin_freetext1` als `Note`), wird mit „ · “
    angehängt. BT-22 erscheint nur einmal.
  - Fehlt der Gast, entfällt die Zeile. Fehlt nur das Zimmer oder der Zeitraum, entfällt
    jeweils nur dieser Teil samt Trenner. Das ist eine Entscheidung des Builders, sie gilt
    vorbehaltlich der Freigabe.
- **BT-22, Rechnung mit mehreren Gästen:** keine Gastzeile im Kopf.
- **BT-70** (`cac:Delivery/cac:DeliveryParty/cac:PartyName/cbc:Name`): Bei einem Gast
  steht er auch dort, wie bei OPERA. Bei mehreren Gästen entfällt BT-70.
- **Quelle des Gastes:** die Herkunftsfelder der Buchungen (Abschnitt 6), nicht
  `ZPOS_YRES_ID`. „Ein Gast“ heißt: Alle Leistungszeilen (CDT 1) haben dieselbe
  Herkunftsreservierung.
- **Anreise und Abreise:** aus der Herkunftsreservierung. Zahlungs- und Steuerzeilen
  zählen bei der Bestimmung nicht mit.
- **Vorlage:** konfigurierbar, Schlüssel `gastzeile`. Ist sie leer, gibt es keine
  Gastzeile.
- **Escaping:** Namen mit „&“ oder „<“ müssen die XML gültig lassen. Das Template
  escapt heute mit `|e`, das wird beibehalten und getestet.

**OPERA-Referenz:** `app/opera.py` `gastzeile()`, `app/xml_templates/xrechnung_3.0.xml.j2`.

## 5. Schritt 1b – Straße 1/2/3

**Heute** wird nur `xadr_street1` gelesen. Ist Zeile 1 leer und Zeile 2 gefüllt, fehlt die
Straße. Das kommt in der Praxis vor.

**Neu:**
- `invoice_header.sql` liefert `xadr_street1`, `xadr_street2` und `xadr_street3` aus
  derselben Adresse wie heute, also dem bestehenden Primäradress-Fallback mit
  `min(xadr_id)`.
- Leere Zeilen und Zeilen nur aus Leerzeichen fallen weg. Die übrigen rücken nach oben:
  1. Zeile → `cbc:StreetName` (BT-50)
  2. Zeile → `cbc:AdditionalStreetName` (BT-51)
  3. Zeile → `cac:AddressLine/cbc:Line` (BT-163)
- Elemente ohne Inhalt werden nicht geschrieben. Die UBL-Reihenfolge innerhalb von
  `PostalAddress` ist einzuhalten (XSD).
- Sind alle drei leer, bleibt es beim heutigen Verhalten: Der Validator meldet „Kunden-Strasse
  fehlt“.
- Nirgends erscheint „None“. Allgemein gilt im Builder: None wird zu leer, wie
  `_leer_statt_none` bei OPERA.
- **Adressen werden nie gesplittet** (Vorgabe des Nutzers): Straße, Ort, PLZ und Land
  kommen immer aus genau einer XADR-Zeile. Gewählt wird die vollständigere Adresse:
  1. alle Felder gefüllt
  2. Straße gefüllt
  3. mehr gefüllte Felder

  Bei Gleichstand gilt die Rechnungsadresse. Fehlende Felder der gewählten Adresse
  werden nie aus der anderen ergänzt, der Validator meldet sie.
- Gilt nur für den Käufer. Die Verkäuferadresse bleibt unverändert.

## 6. Datenquelle Gast und Zimmer je Buchung (für Schritte 1 und 4)

Gemessen an einer Live-Datenbank (nur SELECT):

- **Gast:** `ZPOS.ZPOS_ORIGINATED_XCMS_ID`, auf allen Buchungen gefüllt. Der Name wird
  über `v8_rep_name` aufgelöst, in derselben Form wie die heutigen Gastnamen-Felder.
- **Herkunftsreservierung:** `ZPOS.ZPOS_ORIGINATED_YRES_ID`.
  - Leer, wenn die Buchung auf einem Finanzkonto entstand. Dann ist
    `ZPOS_ORIGINATED_ZFAC_ID` gesetzt.
  - Fallback, wenn ORIGINATED leer ist: `ZPOS_YRES_ID`.
- **Zimmer:** `YDET.YDET_YRMS_ID` der Herkunftsreservierung am `trunc(ZPOS_POSTDATE)` →
  `YRMS.YRMS_SHORTDESC`.
  - Fallback: die letzte YDET-Zeile vor dem Buchungstag. Für Buchungen am Abreisetag gibt
    es keine YDET-Zeile.
  - Bei einem Zimmerwechsel zählt das Zimmer am Buchungstag.
  - `YRES_YRMS_ID` ist nach dem Check-out leer und wird nicht genutzt.
- **Steuerzeilen** (CDT 2) tragen dieselben ORIGINATED-Werte wie ihre Hauptzeile.
- **Buchungen ohne Herkunftsreservierung** (auf einem Konto entstanden) haben keinen
  Gast und kein Zimmer. Sie bekommen keinen Positionstext. Das ist eine Entscheidung des
  Builders, sie gilt vorbehaltlich der Freigabe.
- **Größenordnung im gemessenen Haus:** rund 9–10 % der Rechnungen (etwa 4.000 im Jahr)
  enthalten Buchungen aus mehr als einer Herkunftsreservierung, maximal 240.

SQL-Kern für das Zimmer:

```sql
nvl((select r.yrms_shortdesc from ydet t join yrms r on r.yrms_id=t.ydet_yrms_id
      where t.ydet_yres_id=p.zpos_originated_yres_id and t.ydet_date=trunc(p.zpos_postdate)),
    (select max(r.yrms_shortdesc) keep (dense_rank last order by t.ydet_date)
       from ydet t join yrms r on r.yrms_id=t.ydet_yrms_id
      where t.ydet_yres_id=p.zpos_originated_yres_id and t.ydet_date <= trunc(p.zpos_postdate)))
```

Die neuen Spalten kommen in `sql/invoice_lines.sql`, samt Override-Marker und Rückfall
bei fehlender Spalte (siehe Abschnitt 3).

## 7. Schritt 2 – Auslagen

**Ziel:** prüfen, ob Slim Auslagen (Paid-Out `ZPOS_PAIDOUT=1`, Kurtaxe/City Tax,
Fremdleistungen wie Theaterkarten oder Parken für Dritte) betragsgenau und KoSIT-gültig
abbildet. Korrigiert wird nur, wo es nicht stimmt.

- **Vorgehen:**
  - Echte Beispielrechnungen je Auslagenart beschaffen (Anfrage über die Session mit
    DB-Zugriff läuft).
  - Die Slim-XML dagegen rechnen: Positionen, Steuergruppen, Summen und Zahlbetrag.
  - Befunde dem Nutzer vorlegen, bevor geändert wird.
- **Erwartetes Muster, wie OPERA:** Auslagen als normale Position mit Kategorie Z und
  0 %. Nicht O, weil O die ganze Rechnung binden würde (BR-O-*). Nicht E, weil E einen
  Befreiungsgrund braucht und eine Auslage kein Entgelt ist.
- **Steuerrechtlich:** Ob Z die richtige Kategorie ist, klärt der Nutzer mit dem
  Steuerberater. Das Dokument legt das nicht fest.
- **Bekannte Stolperstellen bei OPERA:** Der Rechnungskopf führte City Tax nicht im
  Netto, wohl aber im Brutto. Paid-Outs fehlten im 0-%-Topf. In Slim prüfen, ob
  `invoice_tax.sql` und `invoice_totals.sql` Ähnliches tun (Divergenz-Guard beachten).
- **Wichtige KoSIT-Regeln:** BR-Z-08, BR-CO-17, BR-S-01, BR-Z-01, BR-27.

**Befund aus einem Haus (12 Monate):**

| Art | Suite8-Buchung | Slim heute |
|---|---|---|
| Kurtaxe (rund 20.000 Rechnungen) | Leistung (CDT 1) mit 0-%-Steuerzeile (MS0) | Z 0 %, vermutlich korrekt |
| Auslagen Gastronomie, Durchlaufender Posten (rund 5.300 Rechnungen) | Leistung (CDT 1) **ohne** Steuerzeile | Kategorie Z, Satz leer → Validator „USt-Satz nicht ermittelbar“ → **Rechnung blockiert** (an synthetischer Rechnung nachgestellt) |
| Eintrittskarten, Parken | normale 19 %/7 % | normal |
| Paid-Out | Zahlungszeile (CDT 5) mit `ZPOS_PAIDOUT=1`, eine Auszahlung an den Gast (rund 800 Zeilen) | Abbildung in Summe und Zahlbetrag ungeprüft |

**Vorgehen:**
- Leistungszeilen ohne Steuerzeile werden als Z 0 % behandelt, nicht blockiert. Sie
  landen in der Steuergruppe Z.
- Kurtaxe und Paid-Out werden an echten Beispielrechnungen nachgerechnet. Die IDs liegen
  bei der Session mit DB-Zugriff und kommen nicht ins Repo.
- Befunde gehen vor jeder weiteren Änderung an den Nutzer.

**Offen:** Ob „ohne Steuerzeile“ fachlich Z bleiben darf, gehört zur Steuerberater-Frage
(Abschnitt 12).

## 8. Schritt 3 – Nur-XML-Versand

**Heute:** Suite8 legt die Rechnungsmail (`WMAI`, `WMAI_BLOCKSEND=1`) mit PDF-Anhang
an. Slim hängt in einer Transaktion die XML an (`WTXT` + `WMAA`) und setzt
`BLOCKSEND=0` (`modules/suite8_mailer.py` `attach_xml_to_wmai`).

**Neu:**

| Fall | Mail enthält |
|---|---|
| Standard | PDF und XML, wie heute |
| Rechnungsempfänger hat das Membership mit Kurzbezeichnung „PDF“ | nur XML |
| globaler Schalter „Nur XML für alle“ ist an (Standard: aus) | nur XML |

- **Membership:** Prüfung wie bei `DXR` (`XMNR`/`XMTY`, `XMTY_SHORTDESC`) am
  Rechnungsempfänger `zwin_invoice_to_xcms_id`. Die Kurzbezeichnung ist konfigurierbar,
  Standard `PDF`. Den Typ legt das Haus in Suite8 selbst an; es gibt ihn noch nicht.
- **Wo das PDF hängt (gemessen, ein Haus):**
  - Das Rechnungs-PDF ist **kein** `WMAA`-Eintrag, sondern der Hauptanhang der Mail
    selbst: `WMAI_ATTACHMENT_WTXT_ID` und `WMAI_ATTACHMENT_FILE_NAME` (voller Pfad,
    endet auf `.pdf`).
  - `WMAA` ist bei Rechnungsmails sonst leer, die XML ist also der einzige `WMAA`-Eintrag.
  - Die Rechnungskopie in Suite8 ist ein eigener Blob (`ZIPL` → `ZINB.ZINB_DATA`). Der
    Mail-Blob von Rechnungsmails ist nirgends sonst referenziert.
  - Korrespondenzmails teilen ihren Blob dagegen mit `YRCO`.
- **Entfernen, ohne etwas zu löschen:** In derselben Transaktion wie das Anhängen der XML
  setzt Slim auf genau der WMAI, die es ohnehin bearbeitet:
  - `WMAI_ATTACHMENT_WTXT_ID = NULL` und `WMAI_ATTACHMENT_FILE_NAME = NULL`.
  - Bedingung: `WMAI_SENT=0` und `BLOCKSEND=1`, und der Dateiname endet auf `.pdf`
    (Groß-/Kleinschreibung egal).
  - `WMAI_ATTACHMENT_RTF_WTXT_ID` wird mitgeprüft. Ist es gesetzt, wird es nicht
    angefasst und die Mail mit Hinweis protokolliert.
  - Der `WTXT`-Blob wird **nie** gelöscht.
  - Ist der Hauptanhang kein PDF oder ändert das Update 0 Zeilen, wird nur die XML
    angehängt und das PDF bleibt, mit Warnung im Protokoll. Die Rechnung wird deshalb
    nicht blockiert. Das ist eine Entscheidung des Builders, sie gilt vorbehaltlich der
    Freigabe.
  - Zu prüfen im Testbetrieb: dass Suite8 eine Mail ohne Hauptanhang, aber mit
    `WMAA`-Anhang korrekt versendet.
- **Protokoll:** Der Audit-Eintrag nennt „PDF entfernt (Membership PDF)“ bzw.
  „(global)“.
- **Membership:** Im gemessenen Haus gibt es weder `DXR` noch `PDF` als `XMTY`. Das Haus
  muss den Typ anlegen. `XMNR` kann an jedem Profil hängen. Geprüft wird zuerst
  `ZWIN_INVOICE_TO_XCMS_ID`, dann `ZINV_XCMS_ID`.

## 9. Schritt 4 – Positionen zusammenfassen, Gruppenrechnung

**Heute** ist jede Buchung (ZPOS, CDT 1) eine eigene InvoiceLine.

**Neu, für alle Rechnungen:**
- Buchungszeilen mit gleichem Schlüssel werden zu einer Position zusammengefasst.
  Schlüssel: (Herkunftsreservierung, Gast `ZPOS_ORIGINATED_XCMS_ID`, Zimmer, Artikel,
  Brutto-Einzelpreis `zpos_grossunitprice`, Steuerkategorie, Steuersatz).
  - Der Gast steht mit im Schlüssel, damit Mitreisende mit eigenem Profil nie unter
    fremdem Namen erscheinen.
  - Menge = Summe von `ZPOS_QUANTITY`. Heute ist `InvoicedQuantity` fest 1 und
    `PriceAmount` der Gesamtbetrag der Zeile. Das ändert sich für alle Rechnungen.
  - Betrag = Summe der Nettobeträge der Einzelbuchungen (wie Suite8 sie rundet).
  - Netto-Einzelpreis (BT-146) = Betrag / Menge, mit bis zu 4 Nachkommastellen, sodass
    Menge × Preis gerundet exakt den Betrag ergibt. PEPPOL-EN16931-R120 muss mit KoSIT
    grün sein. Das ist eine Entscheidung des Builders.
- Bei unterschiedlichen Preisen, etwa am Wochenende, bleiben getrennte Positionen.
- **Korrekturen und Stornos werden nicht verrechnet** (Vorgabe des Nutzers). Das
  Vorzeichen von Menge bzw. Betrag gehört zum Schlüssel:
  - Positive Buchungen werden nur mit positiven zusammengefasst, negative nur mit
    negativen.
  - Original und Korrektur bleiben beide sichtbar, das Original als Position, die
    Korrektur wie heute als Abschlag.
- **Positionszeitraum** (BT-134/135): die Spanne der tatsächlich berechneten
  Buchungstage der Position.
- **Rechnungszeitraum** (BT-73/74): wird so erweitert, dass alle Positionszeiträume
  hineinpassen (PEPPOL-EN16931-R110/R111). Bei OPERA heißt das
  `rechnungszeitraum_erweitern`.
- **Mehrere Gäste** (mehr als eine Herkunftsreservierung unter den Leistungszeilen):
  - Jede Position erhält BT-127 (`cbc:Note` der InvoiceLine) im Format „Zi. 101 · Erika
    Muster“.
  - Der Artikelname (BT-153) bleibt der reine Leistungsname.
  - Sortierung: Zimmer numerisch (9 vor 10), Pseudozimmer und Positionen ohne Zimmer ans
    Ende, dann Gastname, dann Leistung.
- **Ein Gast:** kein Positionstext, denn der Gast steht im Kopf (Abschnitt 4).
- **Zählen von „ein Gast“ und „mehrere Gäste“:** Es zählen nur Leistungszeilen mit
  Herkunftsreservierung, unterschieden nach (Reservierung, Gast). Konto-Buchungen ohne
  Herkunft zählen nicht mit und bekommen nie einen Positionstext. Gibt es keine einzige
  Zeile mit Herkunft, entfallen Gastzeile und Positionstexte. Das ist eine Entscheidung
  des Builders.
- **Gutschriften** (`templates/creditnote_3.0.xml.j2`): Für sie gelten die Schritte 1 und 4
  genauso, damit ein Storno die Originalrechnung spiegelt. Das ist eine Entscheidung des
  Builders.
- **Negative Positionen:** Wie heute werden sie Abschläge (BR-27). Bei mehreren Gästen
  steht der Gast im Grund (BT-97), etwa „Rabatt · Zi. 101 · Erika Muster“.
- **Anzahlungen:** Die Anzahlungsverrechnung aus v1.10.9 (`deposit_allowances`) bleibt
  unberührt. Anzahlungszeilen werden nicht zusammengefasst.
- **Summen:** Die Steuer je Gruppe und alle Summen müssen nach dem Zusammenfassen gleich
  bleiben. Wo Slim heute Steuer aus Netto × Satz neu rechnet, darf durch das
  Zusammenfassen keine neue Rundungsdifferenz entstehen. Das wird mit Tests abgesichert.
- **Schutz vor fremden Gästen:** Ein Positionstext darf nur den Gast der eigenen
  Herkunftsreservierung nennen. Das wird per Test abgesichert.
- **Konfiguration:** Zusammenfassen an/aus, Standard an.

**OPERA-Referenz:** `app/opera.py` (`POSITIONSARTEN`, `positionsart_vorschlag`),
`app/xml_build.py` (`gast_kennung`, `rechnungszeitraum_erweitern`).

## 10. Schritt 5 – Oberfläche: Anmeldung und Konfiguration

**Anmeldung** (heute gibt es nur die IP-Freigabe in `slim/core_slim/access.py`):

- **Benutzer:**
  - Benutzername, gesalzener Passwort-Hash (Standardbibliothek, z. B. `hashlib.scrypt`
    oder PBKDF2) und Rolle.
  - Ablage in `slim/data/`. Das Format bestimmt der Builder; es darf kein Klartext sein.
- **Rollen:**
  - „ansehen“: Warteschlange, Status, Protokoll und Archiv lesen.
  - „verwalten“: zusätzlich Konfiguration ändern, Rechnungen erneut anstoßen, SQL-Ansicht,
    Update auslösen und Benutzer verwalten.
- **Erster Start:**
  - Gibt es keine Benutzer, etwa nach dem Auto-Update einer bestehenden Installation,
    zeigt die Oberfläche **nur bei Zugriff von localhost** die Seite „Ersten Verwalter
    anlegen“ (Name und Passwort).
  - Von anderen Adressen erscheint der Hinweis „Bitte zuerst am Server einen Verwalter
    anlegen“.
  - Die Neuinstallation legt den ersten Verwalter im Einrichtungsassistenten an.
  - Kein Startpasswort im Log. Das ist eine Entscheidung des Builders, Hinweis in den
    Release-Notes.
  - Bis ein Verwalter existiert, läuft der Rechnungsversand ungestört weiter.
- **Letzter Verwalter:** lässt sich weder löschen noch herabstufen.
- **Sitzungen:**
  - Serverseitig, Cookie `HttpOnly` und `SameSite=Strict`, mit Ablauf.
  - Abmelden ist möglich.
  - Schutz gegen das Durchprobieren von Passwörtern: Verzögerung oder Sperre nach
    mehreren Fehlversuchen.
- **Absicherung der Endpunkte:**
  - Alle API-Endpunkte außer `/healthz` und der Anmeldung verlangen eine Sitzung.
  - Schreibende Endpunkte verlangen die Rolle „verwalten“.
  - Die IP-Freigabe bleibt als zusätzliche Schranke davor.
- **Einrichtungsassistent** (`/setup`, `setup_api.py`): Er bleibt für die
  Ersteinrichtung und richtet den ersten Verwalter mit ein.

**Konfigurationsseite** (nur „verwalten“), in Abschnitten:

| Abschnitt | Inhalt | heutige Datei |
|---|---|---|
| Datenbank | TNS-Alias, Benutzer, Passwort, `tns_admin`, Pfad zum Oracle-Client, Knopf „Verbindung testen“ | `connection.json` |
| Hotel | Hauskürzel, Firmenname, Währung, Zahlungsziel, Profil, Verkäuferkontakt (Name, Telefon, Mail) | `hotel.json` |
| Versand | Versandart, Absender, Erkennungsmuster Betreff/Dateiname (inkl. Testfunktion wie heute), Abrufintervall, Name des Anhangs, „Nur XML für alle“, Kurzbezeichnung des Memberships „PDF“ | `hotel.json` |
| Rechnungsinhalt | Vorlage der Gastzeile mit Platzhaltern, Zusammenfassen an/aus | neu |
| Prüfung | KoSIT an/aus, XRechnung-Version | `app_settings.json` |
| Server | Port, erlaubte IP-Adressen, Log-Level, Aufbewahrung | `app_settings.json` |
| Update | an/aus, Repo, Token | `update.json` |

**Hoteldaten: aus Suite8 gelesen, in der Oberfläche überschreibbar** (Vorgabe des
Nutzers):
- **Heute:** Firmierung, Zahlungsziel und weitere Hausdaten kommen aus Suite8-WUSS (z. B.
  `UDEF_XRECHNUNG_FIRMIERUNG`, `UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE`, `Hotelid`,
  Adresse, IBAN/BIC, USt-ID, Kontakt). Die gleichnamigen Felder in `hotel.json`
  (`hotel_long_name`, `default_payment_terms_days`, `xrechnung_profile_id`) wirken nicht.
- **Anzeige:** Die Seite zeigt je Feld den aktuellen Suite8-Wert und daneben ein Feld
  „abweichend“.
- **Vorrang:** Ist „abweichend“ gefüllt, gilt dieser Wert in der XML vor Suite8. Ist es
  leer, gilt Suite8.
- **Geschrieben** wird nur in Slims eigene Konfiguration, nie nach WUSS.
- **Umfang:** alle Verkäuferdaten, die die XML aus WUSS bezieht. Die genaue Liste ergibt
  sich aus `sql/invoice_header.sql`.
- **Tote Felder:** Wirkungslose Felder werden in dieses Schema überführt oder entfernt,
  ohne bestehende Dateien unlesbar zu machen.
- Die Overrides werden nach dem Fetch in Python angewendet, nicht im SQL, damit
  SQL-Overrides der Häuser unberührt bleiben. Das ist eine Entscheidung des Builders.
- Ein Override-Wert wird dabei protokolliert, ohne ihn auszugeben.

**Regeln der Konfigurationsseite:**
- **Geheimnisse** (DB-Passwort, Token):
  - Sie werden nie an den Browser zurückgegeben, angezeigt wird „gesetzt“ oder „nicht
    gesetzt“.
  - Ein leeres Feld beim Speichern heißt „unverändert“.
  - Die Ablage ist verschlüsselt wie heute (`core/crypto.py`, Fernet).
- **Speichern:**
  - Eingaben serverseitig prüfen.
  - Vorher eine Sicherung der Datei anlegen (`<datei>.<zeitstempel>.sicherung`).
  - Atomar schreiben.
  - Einen Audit-Eintrag mit Benutzer, Abschnitt und geänderten Schlüsseln anlegen, ohne
    Werte von Geheimnissen.
- **Erklärtexte:** Jede Einstellung hat einen. Die Quelle bestimmt der Builder; ein Test
  prüft, dass keine Einstellung ohne Text ist.
- **Neustart:**
  - Änderungen, die einen Neustart brauchen (Port, Datenbank, Server), werden markiert.
  - Die Seite bietet „Jetzt neu starten“. Slim beendet sich selbst, und der Dienst (NSSM)
    startet neu, analog zu `_schedule_self_shutdown`.
  - Andere Änderungen wirken ohne Neustart. Das muss der Builder je Einstellung
    sicherstellen.
- **Update:** Nach jedem Update startet Slim neu. Lehre aus OPERA: Neue Templates mit
  altem Code ergeben HTTP 500. Prüfen, ob `slim/core_slim/updater.py` das schon tut.
- **Bestehende Installationen:**
  - Die vorhandenen JSON-Dateien werden unverändert weitergelesen.
  - Neue Schlüssel haben Standardwerte, sodass sich das Verhalten ohne Zutun nicht ändert.
    Ausnahme sind die gewollten fachlichen Korrekturen aus den Schritten 1 und 4.

**OPERA-Referenz:** `app/auth.py`, `app/config.py`, `app/einstellungen.py`,
`docs/15_EINSTELLUNGEN.md`, `app/templates/konfiguration.html`.

## 11. Dem Builder überlassen

- Aufteilung in Module und Dateien, Namen der Konfigurationsschlüssel, Ablageformat der
  Benutzer.
- Gestaltung der Oberfläche im Stil der bestehenden Seiten.
- Ob Gast- und Zimmerdaten pro Zeile im SQL oder in Python aufgelöst werden. Maßgeblich
  sind Performance und Rückfallfähigkeit; bei bis zu 240 Herkünften soll keine Abfrage
  pro Zeile entstehen.
- Reihenfolge der Tests und Schnitt der Commits innerhalb eines Schritts.

## 12. Offene Punkte

1. **PDF-Anhang:** Ob Suite8 eine Mail ohne Hauptanhang korrekt versendet, wird im
   Testbetrieb an einem Haus geprüft (Abschnitt 8).
2. **Auslagen:** Kurtaxe und Paid-Out an echten Rechnungen nachrechnen (Abschnitt 7).
3. **Steuerkategorie für Auslagen:** Entscheidung des Nutzers bzw. des Steuerberaters.
4. **Andere Häuser:** Ob die ORIGINATED-Spalten überall existieren, ist unbestätigt.
   Deshalb ist der Rückfall Pflicht.
