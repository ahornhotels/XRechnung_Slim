# README_FIRST - bitte vor der Installation lesen

Suite8 XRechnung Slim ist eine schlanke, fokussierte Variante der
Vollversion. Diese Datei beschreibt **was sie macht, was sie bewusst nicht
macht, und welche Stolpersteine es im Suite8-Umfeld gibt.**

Wenn nach dem Lesen klar ist, dass die Slim-App für Ihr Hotel das
richtige Werkzeug ist: weiter mit [INSTALL.md](INSTALL.md).

---

## Voraussetzungen

- **Windows 10, Windows 11 oder Windows Server 2019/2022** (jeweils x64).
  Für Test/Demo reicht Windows 11; für produktiven 24/7-Betrieb ist
  ein Server-OS die ehrlichere Wahl (kein Standby, keine User-Login-
  Abhängigkeiten, robustere Update-Strategie).
- **Administrator-Rechte** beim Setup
- **Oracle-Zugangsdaten** zur Suite8-DB (TNS-Alias, Benutzer, Passwort)
- **Erreichbarer DBA** für ein einmaliges Trigger-SQL (das die App
  Ihnen fertig formuliert)

**Standby-Hinweis bei Windows 10/11:** Der Dienst läuft auch nach
Abmeldung weiter (Windows-Dienst-Konzept ist von Benutzer-Sessions
unabhängig). Aber Standby/Hibernate legt ihn natürlich schlafen — vor
Dauereinsatz Energie-Plan auf "Nie" stellen.

---

## Was die Slim-App macht

Alle 30 Sekunden:

1. Sie liest in Suite8 alle wartenden Folio-Mails (mit `BLOCKSEND=1`)
2. Sie extrahiert die Rechnungs-Nummer aus dem Mail-Betreff per Regex
3. Sie holt die Rechnungs-Daten aus Suite8
4. Sie validiert (Pflichtfelder + KoSIT) und baut die XRechnung 3.0 als XML
5. Sie speichert die XML lokal in `slim\data\xml\YYYY\MM\<Nummer>.xml`
6. Sie haengt die XML an die Suite8-Mail als zweiten Anhang
7. Suite8 verschickt jetzt die Mail (PDF + XRechnung-XML)

Bei Problemen bleibt die Mail in Suite8 stehen, die Slim-UI zeigt eine
"Neu versuchen"-Zeile, und der `WMAI_ERROR`-Text ist auch in Suite8
sichtbar.

---

## Was die Slim-App NICHT macht (vs. Vollversion)

| Funktion | Vollversion | Slim |
|---|---|---|
| Eigener Mail-Versand (MS Graph / SMTP) | ja | **nein** - Slim ist 100% auf Suite8-Mailservice angewiesen |
| Manueller XRechnung-Download | ja | **nein** - alles geht ueber den Poller |
| Browser-Suchmaske im Archiv | ja | **nein** - XMLs liegen im Dateisystem |
| Benutzeranmeldung / Rollen | LDAP + 6 Rechte | **nein** - bind auf 127.0.0.1, wer Server-Zugang hat darf alles |
| Auto-Updater | ja | **nein** - Update per Hand bzw. ueber die Vollversion |
| Backup-Job | ja (SQLite) | **nein** - `slim\data\` selbst sichern (z.B. `robocopy`) |
| Statistik / Reports | ja | **nein** - Auswertung auf der JSONL-Log-Datei |

Die Slim-App ist bewusst minimal — wer eine dieser Funktionen braucht,
soll die Vollversion installieren.

---

## Stolpersteine in Suite8 (kritisch)

### 1. BLOCKSEND-Trigger ist Pflicht

Ohne den DB-Trigger sendet Suite8 die Mail sofort, **bevor** die Slim-App
sie ueberhaupt sieht. Die App tut dann sichtbar nichts.

Der Setup-Assistent zeigt das SQL in Schritt 6. Dieses SQL **muss** vom
Suite8-DBA einmal ausgefuehrt werden, sonst funktioniert nichts.

### 2. Mail-Betreff muss die Rechnungs-Nummer enthalten

Standard-Pattern: `Rechnung Nr. 12345`. Wenn Ihr Suite8-Mail-Template
nur "Ihre Rechnung" ohne Nummer schickt, kann die App die Rechnung
nicht zuordnen. Pruefung im Wizard-Schritt 5 mit einem **echten** Beispiel
aus Suite8 - der Live-Tester muss gruen werden.

Workaround: Mail-Template in Suite8 anpassen (`<ZINV_NUMBER>` einfuegen).

### 3. Stornorechnungen brauchen `ZINV_VOID_ZINV_ID`

Wenn Ihr Hotel Stornorechnungen erzeugt, muss in Suite8 explizit der
Bezug zur Original-Rechnung gesetzt sein (`ZINV_VOID_ZINV_ID`). Sonst
schlaegt die XRechnung-Validierung mit "BillingReference fehlt" fehl.
Front-Office-Mitarbeiter beim Storno-Workflow schulen.

### 4. Kunden-E-Mail in der richtigen Tabelle

XRechnung braucht eine `CustomerEndpointID` (BR-DE-15). Die App liest
sie aus `XCOM` (mit `XCMT_TYPE=1`) oder als Fallback aus
`XCMS.XCMS_EMAIL`. Wenn die E-Mail nur in einem Freitext-Notizfeld
steht, fehlt sie im XML.

Workaround (NEU): pro Rechnung **Override** im Slim-UI eintragen
(siehe "Override-Funktion" unten).

### 5. Land als Langname

In `WUSS.Hotelcountry` muss der **Langname** stehen (z.B. "Deutschland"),
nicht der ISO-Code. Die App loest dann ueber `XCOU.XCOU_LONGDESC`
nach "DE" auf.

### 6. WUSS-INSERT-Rechte fuer den Oracle-User

Der Setup-Assistent versucht, drei `UDEF_XRECHNUNG_*`-Keys in der
`WUSS`-Tabelle anzulegen. Wenn Ihr Oracle-User dort keine INSERT-Rechte
hat, zeigt der Wizard ein passendes SQL fuer den DBA an. Kein Drama,
aber ein zusaetzlicher Schritt.

---

## Betrieblich-operative Punkte

### Suite8-Mailservice muss laufen

Die App haengt nur die XRechnung an — versendet wird die Mail vom
Suite8-Mailservice. Wenn der ausgeschaltet ist, sammeln sich
abgearbeitete WMAIs in der DB an aber nichts geht raus. Pruefen Sie
das **ausserhalb** der Slim-App im normalen Suite8-Monitoring.

### Manueller "Mail senden"-Klick in Suite8

Wenn jemand im Suite8-Backoffice eine `BLOCKSEND=1`-Mail manuell auf
"Senden" klickt, geht sie ohne XRechnung raus. Trigger feuert nur bei
INSERT/UPDATE, nicht bei dem manuellen Send-Action. Disziplinarisch
loesen (Mitarbeiter-Schulung) oder Trigger erweitern lassen.

### Pro Hotel eine eigene Installation

Wenn mehrere Hotels denselben Server teilen: jeweils eine eigene Slim-
Installation in einem getrennten Verzeichnis mit eigener Port-Nummer.
Sonst kollidieren die Konfigurationen.

### Setup nochmal starten

Wenn Sie das Setup neu beginnen wollen: die Datei
`slim\config\.setup_done` loeschen, dann `setup_slim.cmd` neu starten.
Achtung: bestehende Werte in `WUSS` werden **nicht** automatisch wieder
geloescht.

---

## Override-Funktion (fuer Validierungsfehler)

Wenn der Validator eine Rechnung ablehnt, weil ein Feld fehlt
(z.B. Kunden-E-Mail), muss der Operator NICHT zwingend in Suite8
nacharbeiten. Im Slim-UI gibt es pro Pending-Zeile einen
**"Override"**-Knopf. Damit lassen sich einzelne Felder fuer **genau
diese eine WMAI** ueberschreiben. Der naechste Poll-Lauf verwendet
die Overrides automatisch.

Override-Dateien liegen in `slim\data\overrides\<wmai_id>.json` und
werden beim erfolgreichen Attach **automatisch geloescht**.

---

## Bulk-Retry

Wenn viele WMAIs gleichzeitig in `wmai_error` haengen
(z.B. nach einem Trigger-Fix oder Pattern-Anpassung), gibt es im
Slim-UI einen **"Alle erneut versuchen"**-Knopf neben der Pending-
Liste. Cleart `WMAI_ERROR=NULL` fuer alle Pending-WMAIs in einem
Durchgang. Der naechste Poll-Lauf greift sie alle frisch auf.

---

## Empfohlene Reihenfolge fuer Ihr erstes Hotel

1. README_FIRST.md (diese Datei) gelesen
2. Mit dem IT-Verantwortlichen abklaeren:
   - Oracle-Zugangsdaten verfuegbar?
   - Suite8-DBA fuer den Trigger erreichbar?
3. Mail-Template-Check in Suite8: traegt der Folio-Mail-Subject die
   Rechnungs-Nummer? Wenn nein: Template anpassen lassen, **bevor**
   die Slim-App live geht
4. Setup-Assistent durchklicken (siehe [INSTALL.md](INSTALL.md))
5. Eine echte Test-Rechnung in Suite8 erzeugen, Folio-Mail verschicken,
   im Slim-UI beobachten ob der Eintrag mit `attach_ok` auftaucht
6. Mail im Posteingang des Test-Empfaengers oeffnen, **beide** Anhaenge
   pruefen (PDF + XRechnung-XML)

---

## Wenn der Wizard schon im DB-Test (Schritt 2) haengt

Die App liefert einen Oracle-Client mit (Thick-Mode-Default), daher sind
die haeufigsten Verbindungs-Fehler:

| Fehlertext | Bedeutung | Loesung |
|---|---|---|
| `ORA-12154: TNS:could not resolve...` | Alias nicht in `tnsnames.ora` | **Easy Connect** im "TNS-Alias"-Feld: `host:1521/SERVICE_NAME`, TNS-Admin leer |
| `ORA-01017: invalid username/password` | Zugangsdaten falsch | mit DBA klaeren |
| `ORA-12541: no listener` | DB-Listener nicht erreichbar | Host/Port/Firewall |
| `ORA-12170: Connect timeout` | Netzwerk-Problem | VPN/Routing/Firewall |

**Drei Eingabe-Varianten** im "TNS-Alias"-Feld sind erlaubt:
- TNS-Alias aus `tnsnames.ora` (klassisch, plus TNS-Admin-Pfad-Feld)
- **Easy Connect** `host:1521/SERVICE_NAME` (robust, TNS-Admin leer lassen)
- Voller Connect-String `(DESCRIPTION=...)` (fuer 21c-PDB-Setups)

Detail-Diagnose:
```cmd
install\python\python.exe scripts\diagnose_tns.py
```

## Wenn etwas anhaengt

| Was Sie sehen | Was es bedeutet | Was tun |
|---|---|---|
| Pending-Liste leer, keine Audit-Eintraege | Trigger fehlt oder feuert nicht | Trigger-SQL pruefen, Suite8 testweise Folio-Mail erzeugen, in `WMAI`-Tabelle `BLOCKSEND` pruefen |
| `pattern_no_match` fuer alle | Subject-Pattern passt nicht zum Mail-Template | Im UI Pattern-Konfiguration testen mit echten Beispielen |
| `validator_fail` mit "Kunden-E-Mail fehlt" | XCOM-Eintrag fehlt | Override im UI eintragen ODER in Suite8 nachpflegen |
| `kosit_fail` mit BR-DE-X | Schematron-Regel verletzt | Fehlertext zeigt die Regel; meistens ist ein Pflichtfeld in WUSS leer |
| `zinv_not_found` | Pattern liefert eine Zahl, die nicht in Suite8 existiert | Pattern auf `(?P<zinv_id>...)` statt `(?P<zinv_number>...)` umstellen wenn der Filename gemeint ist |
| Service-Crash beim Start | KoSIT-JAR oder JRE fehlt | Vollversion installieren (sie liefert beides mit) |

---

## Support / Updates

Updates kommen ueber `git pull` auf das Repository oder ueber die
Vollversions-Updater-Funktion (geteilte Module wie `xml_builder` und
`kosit_validator` ziehen automatisch mit).

Bei Bugs / Wuenschen: GitHub-Issue auf `ahornhotels/Suite8XRechnung`
oder direkt an die IT-Verantwortlichen.
