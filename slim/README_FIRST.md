# README_FIRST – bitte vor der Installation lesen

Suite8 XRechnung Slim ist eine schlanke, fokussierte Variante der
Vollversion. Diese Datei beschreibt **was sie macht, was sie bewusst nicht
macht, und welche Stolpersteine es im Suite8-Umfeld gibt.**

Wenn nach dem Lesen klar ist, dass die Slim-App für Ihr Hotel das
richtige Werkzeug ist: weiter mit [INSTALL.md](INSTALL.md).

---

## Voraussetzungen

- **Windows 10, Windows 11 oder Windows Server 2019/2022** (jeweils x64).
  Für Test/Demo reicht Windows 11; für produktiven 24/7-Betrieb ist
  ein Server-OS die ehrlichere Wahl (kein Standby, keine Abhängigkeit von
  Benutzeranmeldungen, robustere Update-Strategie).
- **Administrator-Rechte** beim Setup
- **Oracle-Zugangsdaten** zur Suite8-DB (TNS-Alias, Benutzer, Passwort)
- **Erreichbarer DBA** für ein einmaliges Trigger-SQL (das die App
  Ihnen fertig formuliert)

**Standby-Hinweis bei Windows 10/11:** Der Dienst läuft auch nach der
Abmeldung weiter (Windows-Dienste sind von Benutzersitzungen unabhängig).
Standby oder Ruhezustand legen ihn aber schlafen – vor dem Dauereinsatz den
Energieplan auf „Nie“ stellen.

---

## Was die Slim-App macht

Alle 30 Sekunden (einstellbar):

1. Sie liest in Suite8 alle wartenden Folio-Mails (mit `BLOCKSEND=1`)
2. Sie liest die Rechnungsnummer per Regex aus dem Mail-Betreff (oder dem
   Dateinamen)
3. Sie holt die Rechnungsdaten aus Suite8
4. Sie prüft (Pflichtfelder + KoSIT) und baut die XRechnung 3.0 als XML
5. Sie speichert die XML lokal in `slim\data\xml\YYYY\MM\<Nummer>.xml`
6. Sie hängt die XML an die Suite8-Mail als zweiten Anhang
7. Suite8 verschickt jetzt die Mail (PDF + XRechnung-XML, bei Nur-XML nur
   die XRechnung)

Bei Problemen bleibt die Mail in Suite8 stehen, die Startseite zeigt eine
„Neu versuchen“-Zeile, und der `WMAI_ERROR`-Text ist auch in Suite8
sichtbar.

### Inhalt der XRechnung

- **Käuferadresse:** Straße 1, 2 und 3; leere Zeilen fallen weg. Die Adresse
  kommt immer vollständig aus einer einzigen Suite8-Adresse, Felder werden nie
  gemischt.
- **Gast:** Bei genau einem Gast steht im Rechnungshinweis (BT-22)
  „Gast: Name, Zimmer 101, 02.03.2026 bis 05.03.2026“ (Vorlage einstellbar),
  zusätzlich ist der Gast Lieferempfänger (BT-70). Rechtlicher Käufer (BT-44)
  ist immer der Rechnungsempfänger.
- **Gruppenrechnung** (Buchungen aus mehreren Reservierungen): Jede Position
  trägt „Zi. 101 · Name“ und ihren eigenen Leistungszeitraum, sortiert nach
  Zimmer. Gast und Zimmer kommen aus der Buchung selbst
  (`ZPOS_ORIGINATED_*`), nicht aus der Rechnung.
- **Zusammenfassen:** Gleiche Buchungen werden eine Position mit Menge,
  z. B. „Logis 3 ×“. Stornos werden nicht verrechnet, Anzahlungen bleiben
  einzeln. Abschaltbar.
- **Auslagen und Paid-Out:** Artikel aus der Liste „Auslage-Artikel“
  (Standard `AUS`, `DUR`) ohne Steuerbuchung gehen mit 0 % hinaus. Andere
  Artikel ohne Steuerbuchung blockieren die Rechnung mit einem klaren Hinweis.
- **Nur-XML:** Rechnungsempfänger mit dem Suite8-Membership „PDF“ bekommen nur
  die XRechnung (oder alle, per Schalter). Den Membership-Typ legen Sie in
  Suite8 selbst an.

---

## Was die Slim-App NICHT macht (vs. Vollversion)

| Funktion | Vollversion | Slim |
|---|---|---|
| Eigener Mail-Versand (MS Graph / SMTP) | ja | **nein** – Slim ist 100 % auf den Suite8-Mailservice angewiesen |
| Manueller XRechnung-Download | ja | **nein** – alles geht über den Poller |
| Archiv | ja | **einfach** – XMLs liegen im Dateisystem, Suche nach Nummer auf der Startseite |
| Benutzeranmeldung / Rollen | LDAP + 6 Rechte | **lokal** – eigene Benutzer mit den Rollen „ansehen“ und „verwalten“ |
| Einstellungen in der Oberfläche | ja | **ja** – alle Einstellungen mit Erklärtext |
| Auto-Updater | ja | **ja** – inkrementell aus GitHub (nur geänderte Dateien) |
| Backup-Job | ja (SQLite) | **nein** – `slim\data\` und `slim\config\` selbst sichern (z. B. `robocopy`) |
| Statistik / Reports | ja | **nein** – Auswertung auf der JSONL-Protokolldatei |

Die Slim-App ist bewusst minimal – wer eine dieser Funktionen braucht,
soll die Vollversion installieren.

---

## Stolpersteine in Suite8 (kritisch)

### 1. BLOCKSEND-Trigger ist Pflicht

Ohne den DB-Trigger sendet Suite8 die Mail sofort, **bevor** die Slim-App
sie überhaupt sieht. Die App tut dann sichtbar nichts.

Der Setup-Assistent zeigt das SQL in Schritt 6. Dieses SQL **muss** vom
Suite8-DBA einmal ausgeführt werden, sonst funktioniert nichts.

### 2. Mail-Betreff muss die Rechnungsnummer enthalten

Standard-Pattern: `Rechnung Nr. 12345`. Wenn Ihr Suite8-Mail-Template
nur „Ihre Rechnung“ ohne Nummer schickt, kann die App die Rechnung
nicht zuordnen. Prüfung im Assistenten-Schritt 5 mit einem **echten**
Beispiel aus Suite8 – der Live-Tester muss grün werden.

Workaround: Mail-Template in Suite8 anpassen (`<ZINV_NUMBER>` einfügen).

### 3. Stornorechnungen brauchen `ZINV_VOID_ZINV_ID`

Wenn Ihr Hotel Stornorechnungen erzeugt, muss in Suite8 der Bezug zur
Original-Rechnung gesetzt sein (`ZINV_VOID_ZINV_ID`). Sonst schlägt die
XRechnung-Validierung mit „BillingReference fehlt“ fehl.
Front-Office-Mitarbeiter beim Storno-Workflow schulen.

### 4. Kunden-E-Mail in der richtigen Tabelle

XRechnung braucht eine `CustomerEndpointID` (BR-DE-15). Die App liest
sie aus `XCOM` (mit `XCMT_TYPE=1`) oder als Fallback aus
`XCMS.XCMS_EMAIL`. Wenn die E-Mail nur in einem Freitext-Notizfeld
steht, fehlt sie im XML.

Workaround: pro Rechnung einen **Override** auf der Startseite eintragen
(siehe „Override-Funktion“ unten).

### 5. Land als Langname

In `WUSS.Hotelcountry` muss der **Langname** stehen (z. B. „Deutschland“),
nicht der ISO-Code. Die App löst ihn über `XCOU.XCOU_LONGDESC`
nach „DE“ auf.

### 6. WUSS-INSERT-Rechte für den Oracle-Benutzer

Der Setup-Assistent versucht, drei `UDEF_XRECHNUNG_*`-Keys in der
`WUSS`-Tabelle anzulegen. Wenn Ihr Oracle-Benutzer dort keine INSERT-Rechte
hat, zeigt der Assistent ein passendes SQL für den DBA an. Kein Drama,
aber ein zusätzlicher Schritt. Danach schreibt die App nie mehr nach `WUSS` –
abweichende Verkäuferdaten pflegen Sie unter **Einstellungen → Hotel**.

### 7. Artikel ohne Steuerbuchung

Bucht Suite8 einen Artikel ohne Steuerzeile, der nicht in der Liste
„Auslage-Artikel“ steht, blockiert die App die Rechnung (Meldung
`lines.tax_missing`). Entweder den Artikel in Suite8 mit Steuer versehen oder
– wenn es wirklich eine Auslage ist – seinen Kurznamen unter
**Einstellungen → Rechnungsinhalt** in die Liste aufnehmen.

---

## Betrieblich-operative Punkte

### Suite8-Mailservice muss laufen

Die App hängt nur die XRechnung an – versendet wird die Mail vom
Suite8-Mailservice. Wenn der ausgeschaltet ist, sammeln sich
abgearbeitete WMAIs in der DB an, aber nichts geht raus. Prüfen Sie
das **außerhalb** der Slim-App im normalen Suite8-Monitoring.

### Manueller „Mail senden“-Klick in Suite8

Wenn jemand im Suite8-Backoffice eine `BLOCKSEND=1`-Mail manuell auf
„Senden“ klickt, geht sie ohne XRechnung raus. Der Trigger feuert nur bei
INSERT/UPDATE, nicht bei der manuellen Senden-Aktion. Organisatorisch
lösen (Mitarbeiter-Schulung) oder Trigger erweitern lassen.

### Pro Hotel eine eigene Installation

Wenn mehrere Hotels denselben Server teilen: jeweils eine eigene Slim-
Installation in einem getrennten Verzeichnis mit eigener Port-Nummer.
Sonst kollidieren die Konfigurationen.

### Setup nochmal starten

Wenn Sie das Setup neu beginnen wollen: die Datei
`slim\config\.setup_done` löschen, dann `setup_slim.cmd` neu starten.
Achtung: Bestehende Werte in `WUSS` werden **nicht** automatisch wieder
gelöscht. Benutzer bleiben erhalten.

---

## Override-Funktion (für Validierungsfehler)

Wenn der Validator eine Rechnung ablehnt, weil ein Feld fehlt
(z. B. Kunden-E-Mail), muss der Verwalter NICHT zwingend in Suite8
nacharbeiten. Auf der Startseite gibt es pro wartender Zeile einen
**„Override“**-Knopf. Damit lassen sich einzelne Felder für **genau
diese eine WMAI** überschreiben. Der nächste Poll-Lauf verwendet
die Overrides automatisch.

Override-Dateien liegen in `slim\data\overrides\<wmai_id>.json` und
werden beim erfolgreichen Anhängen **automatisch gelöscht**.

---

## Alle Fehler erneut versuchen

Wenn viele WMAIs gleichzeitig in `wmai_error` hängen
(z. B. nach einem Trigger-Fix oder einer Pattern-Anpassung), gibt es auf der
Startseite den Knopf **„Alle Fehler erneut versuchen“** neben der Liste der
wartenden Mails. Er leert `WMAI_ERROR` für alle wartenden WMAIs in einem
Durchgang. Der nächste Poll-Lauf greift sie alle frisch auf.

---

## Empfohlene Reihenfolge für Ihr erstes Hotel

1. README_FIRST.md (diese Datei) gelesen
2. Mit dem IT-Verantwortlichen abklären:
   - Oracle-Zugangsdaten verfügbar?
   - Suite8-DBA für den Trigger erreichbar?
3. Mail-Template-Check in Suite8: Trägt der Betreff der Folio-Mail die
   Rechnungsnummer? Wenn nein: Template anpassen lassen, **bevor**
   die Slim-App live geht
4. Setup-Assistent durchklicken und ersten Verwalter anlegen (siehe
   [INSTALL.md](INSTALL.md))
5. Eine echte Test-Rechnung in Suite8 erzeugen, Folio-Mail verschicken,
   auf der Startseite beobachten, ob der Eintrag mit `attach_ok` auftaucht
6. Mail im Posteingang des Test-Empfängers öffnen, **beide** Anhänge
   prüfen (PDF + XRechnung-XML)
7. Falls Nur-XML gewünscht: einem Testkunden das Membership „PDF“ geben und
   prüfen, dass die Mail nur die XRechnung enthält

---

## Wenn der Assistent schon im DB-Test (Schritt 2) hängt

Die App bringt einen 64-bit-Oracle-Client mit (Thick-Mode), daher sind die
häufigsten Verbindungsfehler:

| Fehlertext | Bedeutung | Lösung |
|---|---|---|
| `ORA-12154: TNS:could not resolve...` | Alias nicht in `tnsnames.ora` | **Easy Connect** im Feld „TNS-Alias“: `host:1521/SERVICE_NAME`, TNS-Admin leer |
| `ORA-01017: invalid username/password` | Zugangsdaten falsch | mit DBA klären |
| `ORA-12541: no listener` | DB-Listener nicht erreichbar | Host/Port/Firewall |
| `ORA-12170: Connect timeout` | Netzwerk-Problem | VPN/Routing/Firewall |
| `DPY-3015: password verifier type ...` | kein 64-bit-Oracle-Client (Thin-Mode) | Online-Installer erneut ausführen |

**Drei Eingabe-Varianten** im Feld „TNS-Alias“ sind erlaubt:
- TNS-Alias aus `tnsnames.ora` (klassisch, plus Feld „Ordner der tnsnames.ora“)
- **Easy Connect** `host:1521/SERVICE_NAME` (robust, TNS-Admin leer lassen)
- Voller Connect-String `(DESCRIPTION=...)` (für 21c-PDB-Setups)

## Wenn etwas hängt

| Was Sie sehen | Was es bedeutet | Was tun |
|---|---|---|
| Liste der wartenden Mails leer, keine Protokolleinträge | Trigger fehlt oder feuert nicht | Trigger-SQL prüfen, in Suite8 testweise eine Folio-Mail erzeugen, in der `WMAI`-Tabelle `BLOCKSEND` prüfen |
| `pattern_no_match` für alle | Betreff-Pattern passt nicht zum Mail-Template | Auf der Startseite unter „Pattern-Konfiguration“ mit echten Beispielen testen |
| `validator_fail` mit „Kunden-E-Mail fehlt“ | XCOM-Eintrag fehlt | Override eintragen ODER in Suite8 nachpflegen |
| `validator_fail` mit `lines.tax_missing` | Artikel ohne Steuerbuchung | siehe Stolperstein 7 |
| `kosit_fail` mit BR-DE-X | Schematron-Regel verletzt | Fehlertext zeigt die Regel; meistens ist ein Pflichtfeld in WUSS leer |
| `zinv_not_found` | Pattern liefert eine Zahl, die nicht in Suite8 existiert | Pattern auf `(?P<zinv_id>...)` statt `(?P<zinv_number>...)` umstellen, wenn der Dateiname gemeint ist |
| Anmeldung nicht möglich, „Ersteinrichtung nur am Server“ | Es gibt noch keinen Benutzer | Am Server selbst `http://127.0.0.1:8022/login` öffnen |
| Service-Crash beim Start | KoSIT-JAR oder JRE fehlt | Online-Installer (`install_online.ps1`) erneut ausführen – er lädt JRE und KoSIT-JAR nach |

---

## Support / Updates

Updates laufen über den eingebauten **inkrementellen Updater**: Die Startseite
meldet „Update verfügbar“, ein Verwalter klickt „Jetzt aktualisieren“. Er holt
aus dem GitHub-Repo `ahornhotels/XRechnung_Slim` nur die seit der laufenden
Version geänderten Dateien. Erstinstallationen laufen über den
Online-Installer (siehe [`INSTALL_FROM_GITHUB.md`](../INSTALL_FROM_GITHUB.md)).

Bei Bugs / Wünschen: GitHub-Issue auf `ahornhotels/XRechnung_Slim`
oder direkt an die IT-Verantwortlichen.
