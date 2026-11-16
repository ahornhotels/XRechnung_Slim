# Menü, XRechnung-Schalter, BT-10-Freitexte und Archiv – Design

Stand: 16.11.2026 · Grundlage: Gespräch mit dem Betreiber (Ahorn IT)

## 1. Warum

- Die Einstellungsseite ist eine lange Liste nach technischen Abschnitten. Der Betreiber
  will fachlich getrennte Menüpunkte: alles zur XRechnung an einer Stelle, alle Hoteldaten
  an einer anderen.
- Es gibt keinen echten Ausschalter. „Verarbeitung = aus“ pausiert nur Slim; solange der
  Suite8-Trigger aktiv ist, bleiben alle Rechnungsmails gesperrt. Der Betreiber will
  einen Schalter, der den Trigger in der Datenbank aktiv bzw. inaktiv setzt, damit Mails
  im Aus-Zustand wieder normal (nur mit PDF) aus Suite8 rausgehen.
- BT-10 (Käuferreferenz) kommt heute nur aus der DXR-Mitgliedschaft, sonst steht der Name
  des Profils drin. Häuser pflegen Bestell-/Referenznummern oft im Rechnungsfenster
  (Freitext). Diese sollen als Ersatz wählbar sein.
- Das Archiv ist heute ein Kasten auf der Startseite. Es soll ein eigener Menüpunkt werden,
  zum Nachlesen und für Prüfer: Was genau wurde gesendet?

## 2. Ziele / Nicht-Ziele / Anti-Ziele

**Ziele**
- Menüleiste oben (Variante A): Übersicht · Konfiguration XRechnung · Hoteldaten · Archiv ·
  System · Benutzer. Rechts oben auf jeder Seite der XRechnung-Schalter.
- Schalter schaltet den Trigger `WMAI_XRECHNUNG_BLOCK` aktiv/inaktiv und zeigt den echten
  Zustand aus der Datenbank.
- BT-10: DXR immer zuerst, danach ZWIN-Freitext 1–4, jeder einzeln einschaltbar.
- Archivseite mit Suche nach Rechnungsnummer, lesbarer Ansicht und Echtheitsnachweis.

**Nicht-Ziele**
- Slim legt den Trigger nicht selbst an (bleibt DBA-Aufgabe, SQL wie heute).
- Keine weiteren BT-10-Quellen (YRES-Freitexte, ZPOS-Kommentare) – bewusst verworfen.
- Kein nachträgliches Anhängen von XML an Mails, die im Aus-Zustand verschickt wurden.

**Anti-Ziele (wäre ein Fehlschlag, auch wenn es technisch läuft)**
- Ausschalten lässt gesperrte Mails ohne XML rausgehen.
- Schalter zeigt „aus“, obwohl der Trigger in der DB noch aktiv ist (oder umgekehrt).
- Eine Einstellung aus den JSON-Dateien ist nach dem Umbau nicht mehr in der Oberfläche
  erreichbar (Test `test_jeder_json_schluessel_in_der_oberflaeche` muss weiter gelten).
- Hausnamen, echte Rechnungsnummern oder Kundendaten im öffentlichen Repo.

## 3. Entscheidungen des Betreibers

### 3.1 Menü
- Variante A: Menüleiste oben, Schalter rechts oben, auf allen Seiten gleich.

### 3.2 XRechnung-Schalter
- **Aus:** Trigger in der DB auf inaktiv (`ALTER TRIGGER … DISABLE`). Neue Rechnungsmails
  gehen normal raus (PDF). Slim verarbeitet keine Mails mehr. **Bereits gesperrte Mails
  bleiben gesperrt** bis zum Wiedereinschalten.
- **Ein:** Trigger aktiv (`ENABLE`), Slim arbeitet weiter, die liegengebliebenen Mails
  bekommen ihre XML und gehen raus.
- Anzeige des echten DB-Zustands: aktiv · inaktiv · Trigger fehlt.

### 3.3 BT-10 Käuferreferenz
Reihenfolge, immer genau so:
1. DXR-Mitgliedschaft am Rechnungsempfänger (`zwin_invoice_to_xcms_id`) – immer Vorrang.
2. ZWIN_FREETEXT1, 2, 3, 4 – nur die eingeschalteten, in dieser Reihenfolge, der erste
   gefüllte gewinnt.
3. Wie heute: Name des Profils an der Rechnung.

Der Nutzer entscheidet, welche Freitexte er einschaltet (ab Werk alle aus). Der Hinweistext
an den Schaltern steht explizit auf der Seite:

> Freitext 1 – erscheint immer als Hinweis (BT-22) in der XRechnung, eingeschaltet
> zusätzlich als Käuferreferenz.
> Freitext 2 bis 4 – erscheinen nur in der XRechnung, wenn hier eingeschaltet, dann als
> Käuferreferenz.
> Die DXR-Mitgliedschaft hat immer Vorrang, danach gilt der erste gefüllte eingeschaltete
> Freitext (1 → 4).
> In Suite8: Rechtsklick im Rechnungsfenster → „Bearbeite gewähltes Fenster“ → Reiter
> „Text“, die vier Zeilen sind Freitext 1 bis 4.

Befund V8LIVE (lokale Testdatenbank, nur SELECT): ZWIN_FREETEXT1–4 je VARCHAR2(60).
Gefüllt: 1 → 25, 2 → 473 (meist Nummern), 3 → 31, 4 → 1 bei 144.786 Rechnungen.
XMTY „DXR“ existiert in V8LIVE nicht, kein Trigger an WMAI.

### 3.4 Archiv
- Eigener Menüpunkt. Zweck: Nachlesen und Prüfer – genau die gesendete Datei.
- Suche nach Rechnungsnummer, dazu Zeitraum von/bis nach **Rechnungsdatum** (IssueDate aus
  der XML, Entscheidung des Betreibers). Das Rechnungsdatum wird deshalb mit in die
  Archiv-Metadaten geschrieben; für Bestandsdateien liest Slim es einmalig aus der XML.
- Liste: Rechnung · Rechnungsdatum · Art (Rechnung/Gutschrift) · Angehängt am · Empfänger-Mail · Betrag ·
  Echtheit (SHA-256 geprüft, „✔ unverändert“).
- Aktionen: Ansehen (lesbare Rechnung aus der XML, Original-XML aufklappbar) · XML
  herunterladen (unverändert) · KoSIT-Prüfbericht.
- Empfänger-Mail und Zeitpunkt werden ab jetzt beim Archivieren mitgespeichert; ältere
  Dateien zeigen dort, was das Audit-Protokoll hergibt, sonst leer.

## 4. Aufteilung der Einstellungen (Betreiber hat den Vorschlag bestätigt)

| Seite | Inhalt |
|---|---|
| Konfiguration XRechnung | Erkennung Betreff/Dateiname, Name des XML-Anhangs, Nur XML für alle, Membership für Nur-XML · Gastzeile, Positionen zusammenfassen, Auslage-Artikel, Rundungsausgleich (!) · Käuferreferenz BT-10 (Freitext 1–4) · KoSIT-Prüfung, XRechnung-Version |
| Hoteldaten | Verkäuferdaten aus Suite8 mit Abweichung (heute „seller“) · Hauskürzel, Hausname, Währung, Zahlungsziel · Ansprechpartner Name/Telefon/E-Mail · Absender-E-Mail |
| System | Datenbank, Abrufintervall, Server, Update |
| Übersicht | heutige Startseite ohne Archivkasten |

„Verarbeitung“ (`mail_strategy`) verschwindet aus der Oberfläche; der Schalter übernimmt.

## 5. Calls des Assistenten (bitte beim Lesen prüfen)

- **C1** Fehlt der Trigger, zeigt der Schalter „Trigger fehlt“ und das Trigger-SQL für den
  DBA (wie im Einrichtungsassistenten). Kein automatisches Anlegen.
- **C2** Bedienen darf den Schalter nur die Rolle „verwalten“; „ansehen“ sieht den Zustand.
- **C3** Die Datenbank ist die einzige Wahrheit, der Schalter speichert keinen eigenen
  Zustand. Ist der Trigger `DISABLED`, verarbeitet der Poller nichts (gesperrte Mails
  bleiben gesperrt). Bei „fehlt“ oder „nicht prüfbar“ arbeitet der Poller wie heute
  weiter – sonst stünde in Häusern, deren Slim-Benutzer den Trigger nicht sehen darf, nach
  dem Update die Verarbeitung still (bei fehlendem Trigger gibt es ohnehin keine
  gesperrten Mails). Damit kann „Trigger aktiv, Slim aus“ nicht entstehen, auch nicht, wenn
  der DBA den Trigger von Hand schaltet oder neu anlegt. Schlägt `ALTER TRIGGER` fehl
  (z. B. fehlendes Recht), bleibt der Zustand, die Oracle-Meldung wird angezeigt.
- **C3a** Zustand wird über `ALL_TRIGGERS` (Name `WMAI_XRECHNUNG_BLOCK`, Tabelle `WMAI`)
  gelesen, `ALTER TRIGGER` mit Schema des Besitzers. Vier Anzeigen: aktiv · inaktiv ·
  Trigger fehlt · nicht prüfbar (Datenbank nicht erreichbar oder keine Sicht). Bei
  „nicht prüfbar“ wird nicht „fehlt“ gemeldet. Gehört der Trigger nicht Slims Benutzer,
  zeigt Slim den nötigen `GRANT ALTER ANY TRIGGER` für den DBA.
- **C3b** `mail_strategy` verschwindet aus der Oberfläche und kommt in die Ausnahmeliste
  des JSON-Vollständigkeitstests. Der Poller wertet den Schlüssel weiter aus (Altwerte
  wie `graph` bei übernommenen Installationen halten Slim an wie bisher); Slims Assistent
  setzt ihn wie heute auf `suite8`.
- **C4** Jeder Schaltvorgang wird im Audit protokolliert (wer, wann, vorher/nachher).
- **C5** Freitext 1 bleibt zusätzlich Hinweis (BT-22) – keine Verhaltensänderung.
- **C6** „Angehängt am“ ist der Zeitpunkt, zu dem Slim die XML angehängt und die Mail
  freigegeben hat; den tatsächlichen Versand durch den Suite8-Mailservice zeigt das Archiv
  nicht.
- **C8** Archiv zeigt jede archivierte Version einer Rechnungsnummer als eigene Zeile mit
  Status: „gesendet“ (Anhängen geglückt, `attach_ok`) oder „nicht angehängt“ (Datei
  archiviert, Anhängen danach gescheitert). Die jüngste gesendete Version ist markiert.
- **C9** KoSIT-Prüfbericht: Knopf nur, wenn ein Bericht archiviert ist (heute übergibt der
  Poller keinen). Keine Nachprüfung auf Abruf.
- **C7** Bestehende Adresse `/settings` leitet auf „Konfiguration XRechnung“ weiter, damit
  alte Lesezeichen funktionieren.

## 6. Dem Builder überlassen

- Technische Umsetzung der Seiten (eine Seite je Menüpunkt oder gemeinsamer Rahmen), solange
  das bestehende Schema `settings_schema.py` die einzige Quelle der Einstellungen bleibt.
- Wie Archiv-Metadaten gespeichert werden (Seitendatei je XML oder Index), solange die
  Original-XML unverändert und der SHA-256-Nachweis gültig bleibt.
- Lesbare Rechnungsansicht: Darstellung frei, Inhalt aus der archivierten XML (nicht aus
  Suite8).

## 7. Bestehende Fakten im Code

- Trigger-SQL: `slim/api_slim/trigger_sql.py` (`build_block_trigger_sql`), Name
  `WMAI_XRECHNUNG_BLOCK`.
- Pause: `slim/jobs_slim/poller.py:110` (`mail_strategy` ∉ suite8/auto → kein Lauf).
- BT-10: `sql/invoice_header.sql:49`; Freitext 1 = `Note` (Zeile 27), Freitext 2 = `Note2`
  (Zeile 28, ungenutzt); Freitext 3/4 werden noch nicht gelesen.
- Archiv: `slim/core_slim/archive_fs.py` (`save_xml`), API `slim/api_slim/archive_api.py`,
  heutige UI in `slim/frontend/index.html` (Abschnitt „XML-Archiv“).
- Einstellungen: `slim/core_slim/settings_schema.py`, `slim/frontend/settings.html`,
  `slim/api_slim/settings_api.py`.
