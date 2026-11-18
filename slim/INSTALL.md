# Slim-App installieren

Vier Schritte. Mehr nicht.

## Voraussetzungen

- **Windows 10, Windows 11 oder Windows Server 2019/2022** (jeweils x64).
  Für Test und Demo reicht Windows 11; für produktiven Dauerbetrieb ist
  ein Server-OS empfohlen.
- Oracle-Zugangsdaten (TNS-Alias, Benutzername, Passwort) von Ihrer IT.
- Sie sind als Benutzer mit **Administrator-Rechten** angemeldet.

**Hinweis Win 10/11:** Der Slim-Dienst läuft auch nach der Abmeldung
weiter, denn Windows-Dienste sind von Benutzersitzungen unabhängig. Geht
der Rechner aber in Standby oder Ruhezustand, pausiert auch der Dienst. Vor
dem Dauereinsatz unter *Energieoptionen* die Standby-Zeit auf „Nie“ stellen.

**Hinweis:** Die Slim-App ist eigenständig. Der Online-Installer
(siehe [`INSTALL_FROM_GITHUB.md`](../INSTALL_FROM_GITHUB.md)) bringt Python,
JRE, Oracle Instant Client und NSSM selbst mit. Eine separate
Big-App-Installation ist nicht erforderlich.

## Schritt 1 – Setup-Assistent starten

Im Explorer in den Ordner `slim` wechseln und auf

```
setup_slim.cmd
```

**doppelklicken**.

Es kommt ein UAC-Dialog („Möchten Sie zulassen …“ → **Ja**).
Danach öffnen sich:

- ein schwarzes Fenster (das ist der Server – bitte offen lassen)
- der Browser mit dem Setup-Assistenten

## Schritt 2 – Den Assistenten durchklicken

Der Assistent fragt in 8 Schritten alles Nötige ab:

1. **Willkommen** – kurze Erklärung
2. **Datenbank** – Sie tragen TNS-Alias, Benutzername und Passwort
   ein. Knopf „Verbindung testen“ – wenn grün, klicken Sie auf
   „Weiter →“
3. **Stammdaten** – der Assistent zeigt, welche Hotel-Werte schon in
   Suite8 gepflegt sind. Wenn welche fehlen: in Suite8 nachpflegen,
   „Erneut prüfen“. Sonst weiter
4. **UDEF-Keys** – die drei XRechnung-Werte. Die Vorgaben sind sinnvoll
   („14“ Tage, „Buchhaltung“). Knopf „In Suite8 anlegen“ → der Assistent
   schreibt die Werte direkt in Suite8
5. **Rechnungsnummer-Erkennung** – der Standard ist meist richtig
   (`Rechnung Nr. <Nummer>`). Kopieren Sie einen echten Mail-Betreff
   aus Suite8 in das Testfeld, dann „Pattern jetzt testen“. Wenn der
   Treffer grün ist: „Pattern speichern“
6. **SQL für Datenbank-Administrator** – der Assistent zeigt ein
   fertiges SQL. Knopf „In Zwischenablage kopieren“ → das SQL Ihrem
   Suite8-DBA per Mail oder Ticket senden. Der DBA führt es einmal aus
7. **Hotel** – Hauskürzel, Ansprechpartner Buchhaltung usw. „Speichern“
8. **Fertig** – Knopf „Service installieren und starten“. Der Assistent
   meldet „Service wurde installiert und gestartet“

## Schritt 3 – Ersten Verwalter anlegen

Die Oberfläche hat eine Anmeldung. Direkt nach der Einrichtung gibt es noch
keinen Benutzer:

1. **Am Server selbst** `http://127.0.0.1:8022/login` öffnen.
2. Name und Passwort (mindestens 10 Zeichen) für den ersten **Verwalter**
   vergeben.

Das geht nur am Server und nur, solange es noch keinen Benutzer gibt. Von
anderen Rechnern ist es nicht möglich. Der Rechnungsversand läuft bis dahin
schon normal.

Weitere Benutzer legt der Verwalter unter **Benutzer** an:

| Rolle | Darf |
|---|---|
| **ansehen** | Status, wartende Mails, Protokoll und Archiv ansehen |
| **verwalten** | zusätzlich Einstellungen, Benutzer, Overrides, „Neu versuchen“, Updates |

Neue Benutzer bekommen ein Startpasswort und müssen es bei der ersten
Anmeldung ändern. Nach fünf Fehlversuchen von einem anderen Rechner ist die
Anmeldung dort für 15 Minuten gesperrt; am Server selbst gibt es keine Sperre, aber eine
wachsende Wartezeit.

**Update von Version 1.x:** Nach dem Update auf 2.0 ebenfalls einmal Schritt 3
ausführen.

## Schritt 4 – Fertig

Die Startseite unter `http://127.0.0.1:8022/` zeigt Polling-Statistik,
wartende Suite8-Mails und das Protokoll.

Die App läuft jetzt als Windows-Dienst und startet bei jedem Server-Neustart
automatisch.

### Menü

Oben auf jeder Seite steht die Menüleiste, rechts daneben der
XRechnung-Schalter. Konfiguration XRechnung, Hoteldaten, System und Benutzer
sieht nur die Rolle „verwalten“; jede Einstellung hat einen Erklärtext.

| Menüpunkt | Inhalt |
|---|---|
| Übersicht | wartende Mails, letzte Läufe, Protokoll, Updates |
| Konfiguration XRechnung | Erkennung im Betreff/Dateinamen, Name des XML-Anhangs, **Nur-XML** · Gastzeile (BT-22), Positionen zusammenfassen, Auslage-Artikel, Rundungsausgleich · Käuferreferenz (BT-10) · KoSIT-Prüfung, XRechnung-Version |
| Hoteldaten | Verkäuferdaten aus Suite8 (abweichend festlegbar) · Hauskürzel, Hausname, Währung, Zahlungsziel · Ansprechpartner, Absender-E-Mail |
| Archiv | alle gesendeten XRechnungen, Suche nach Rechnungsnummer und Rechnungsdatum |
| System | Datenbank (mit Verbindungstest), Abrufintervall, Server, Update |
| Benutzer | Anmeldungen und Rollen |

Die alte Adresse `/settings` führt auf „Konfiguration XRechnung“.

### XRechnung ein- und ausschalten

Der Schalter rechts oben schaltet den Suite8-Trigger `WMAI_XRECHNUNG_BLOCK`
in der Datenbank (nur Rolle „verwalten“). Er zeigt immer den echten Zustand
aus der Datenbank:

| Anzeige | Bedeutung |
|---|---|
| **● XRechnung EIN** | Trigger aktiv: Suite8 hält jede Rechnungsmail zurück, bis die App die XRechnung angehängt hat |
| **○ XRechnung AUS** | Trigger inaktiv: neue Rechnungsmails gehen ohne XRechnung (nur PDF) raus. Bereits wartende Mails bleiben gesperrt, bis wieder eingeschaltet wird |
| **Trigger fehlt** | der Trigger ist nicht angelegt – ein Klick zeigt das SQL für den Datenbank-Administrator |
| **XRechnung nicht prüfbar** | keine Verbindung oder keine Sicht auf den Trigger; die App arbeitet dann wie bisher weiter |

Nach dem Wiedereinschalten bekommen die liegengebliebenen Mails ihre
XRechnung. Mails, die in der Aus-Zeit verschickt wurden, bekommen nachträglich
nichts. Jeder Schaltvorgang steht im Protokoll (wer, wann, vorher/nachher).

Gehört der Trigger einem anderen Datenbankbenutzer als dem der App, braucht
der App-Benutzer einmalig das Recht zum Schalten – der DBA führt aus:

```sql
GRANT ALTER ANY TRIGGER TO <App-Benutzer>;
```

Gehört auch die Tabelle WMAI einem anderen Benutzer, sieht der App-Benutzer
den Trigger zusätzlich nur mit Leserecht auf `DBA_TRIGGERS`; die Anzeige steht
dann auf „nicht prüfbar“ und ein Klick zeigt beide Befehle:

```sql
GRANT SELECT ON SYS.DBA_TRIGGERS TO <App-Benutzer>;
GRANT ALTER ANY TRIGGER TO <App-Benutzer>;
```

### Käuferreferenz (BT-10)

Die Käuferreferenz (bei Behörden die Leitweg-ID) kommt in dieser Reihenfolge:

1. **DXR-Mitgliedschaft** am Rechnungsempfänger – hat immer Vorrang
2. **Freitext 1 bis 4** aus dem Rechnungsfenster – nur die unter
   Konfiguration XRechnung → Käuferreferenz eingeschalteten, der erste
   gefüllte in der Reihenfolge 1 → 4 (ab Werk alle aus)
3. sonst wie bisher der Name des Profils

Die Freitexte stehen in Suite8 hier: Rechtsklick im Rechnungsfenster →
„Bearbeite gewähltes Fenster“ → Reiter „Text“, die vier Zeilen sind Freitext
1 bis 4. Freitext 1 erscheint immer als Hinweis (BT-22) in der XRechnung;
Freitext 2 bis 4 erscheinen nur, wenn sie als Käuferreferenz eingeschaltet
sind.

### Archiv

Unter **Archiv** liegt jede XRechnung genau so, wie sie an die Mail gehängt
wurde – zum Nachlesen und für Prüfer. Suche nach Rechnungsnummer und nach
**Rechnungsdatum** (von/bis). Je Datei: Art, Zeitpunkt des Anhängens,
Empfänger-Mail, Betrag und Status („gesendet“, „nicht angehängt“ oder bei
alten Dateien ohne Protokolleintrag „unbekannt“). „✔ unverändert“ bestätigt
per SHA-256, dass die Datei seit dem Archivieren nicht verändert wurde.
„Ansehen“ zeigt die Rechnung lesbar, darunter die Original-XML; „XML“ lädt die
Datei unverändert herunter. Wird eine Rechnung erneut erzeugt, bleibt jede
Version mit eigenem Prüfwert erhalten.

Vor jedem Speichern legt die App eine Sicherung der Datei an
(`<datei>.<zeitstempel>.sicherung`, die letzten 20 bleiben). Einstellungen mit
dem Hinweis „Neustart“ wirken erst nach einem Neustart – der Knopf dafür
erscheint nach dem Speichern.

### Nur XML versenden

Standard: Die Mail enthält PDF und XRechnung. Rechnungsempfänger mit dem
Suite8-Membership **„PDF“** (Kurzbezeichnung einstellbar) bekommen nur die
XRechnung – die App nimmt PDF und RTF aus der Suite8-Mail, gelöscht wird
nichts. Alternativ gilt der Schalter „Nur XML für alle“. Den Membership-Typ
legen Sie in Suite8 selbst an. **Bitte zuerst mit einem Testkunden
ausprobieren.**

### Rundungsausgleich (wenn ein Empfänger die Steuer ablehnt)

Suite8 rundet die Steuer je Buchung. Bei vielen kleinen Buchungen (z. B.
Frühstück im Paket) passen Bemessungsgrundlage und Steuer dann um einige Cent
nicht zu den Positionen. Der KoSIT-Validator toleriert das, strenge
Empfänger wie SAP lehnen die Rechnung ab. Unter **Konfiguration XRechnung →
Rechnungsinhalt → Rundungsausgleich** (das rote **!** daneben erklärt
ausführlich, wie Suite8 rechnet und was in Datenbank, PDF und XML herauskommt):

- **aus** – Werte wie aus Suite8 (Standard)
- **position** – Steuer je Satz vom Brutto neu berechnet, der Rest von wenigen
  Cent steckt in der größten Position
- **abschlag** – wie „position“, der Rest steht aber als Abschlag bzw.
  Zuschlag „Rundungsausgleich“ in der Rechnung, alle Positionen bleiben wie in
  Suite8

Der Endbetrag ändert sich nie. Die Steuer in der XRechnung kann um einige Cent
von den Suite8-Steuerbuchungen (und damit vom PDF) abweichen – bitte mit der
Buchhaltung abstimmen.

### Optional: Zugriff aus dem Netzwerk (andere PCs)

Standardmäßig ist die App nur auf dem Server selbst erreichbar. Für den
Zugriff von anderen PCs im Hotel-Netz unter **System → Server**:

- Adresse `0.0.0.0`
- Erlaubte Adressen: exakte IPs oder Netze wie `192.168.10.0/24`

localhost ist immer erlaubt, eine leere Liste sperrt alle anderen PCs. Danach
neu starten (Knopf in der Oberfläche oder `nssm restart Suite8XRechnungSlim`)
und ggf. Port 8022 in der Windows-Firewall freigeben. Auch aus dem Netz ist
eine Anmeldung nötig.

---

## Wenn etwas schief geht

### „Verbindung fehlgeschlagen“ in Schritt 2

Die Slim-App bringt einen 64-bit-Oracle-Client mit (Thick-Mode), daher sind
die häufigsten Probleme:

| Fehlertext | Bedeutung | Lösung |
|---|---|---|
| `ORA-12154: TNS:could not resolve...` | TNS-Alias nicht in `tnsnames.ora` gefunden | **Easy Connect verwenden** im Feld „TNS-Alias“: `<db-host>:1521/<SERVICE_NAME>`, das TNS-Admin-Feld leer lassen |
| `ORA-01017: invalid username/password` | Zugangsdaten falsch | Benutzername und Passwort mit dem DBA klären |
| `ORA-12541: no listener` | DB-Server-Listener nicht erreichbar | Host, Port, Firewall prüfen |
| `ORA-12170: Connect timeout` | Netzwerk-Problem | VPN, Routing, Firewall prüfen |
| `DPY-3015: password verifier type ...` | kein 64-bit-Oracle-Client gefunden (Thin-Mode) | Online-Installer erneut ausführen oder unter „Oracle-Client-Ordner“ einen 64-bit-Client eintragen |

**Drei Eingabe-Varianten im Feld „TNS-Alias“ sind erlaubt:**

a) **TNS-Alias** aus der `tnsnames.ora` – z. B. `V8`
   *plus* TNS-Admin-Pfad mit dem Verzeichnis, in dem `tnsnames.ora` liegt
   (oder leer für die Suche in den üblichen Oracle-Client-Pfaden)

b) **Easy Connect** ★ am robustesten *plus* TNS-Admin leer lassen
   ```
   db-host:1521/SERVICE_NAME
   ```

c) **Voller Connect-String**, z. B. für 21c-PDB-Setups *plus* TNS-Admin leer
   ```
   (DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=...)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=...)))
   ```

Den Service-Namen liefert der DBA per:
```sql
SELECT VALUE FROM V$PARAMETER WHERE NAME = 'service_names';
```

### „Service-Installation nicht durchgekommen“ in Schritt 8

Heißt meist: Der Setup-Assistent lief nicht als Administrator. Lösung:
ein zweites Mal auf `setup_slim.cmd` doppelklicken – beim UAC-Dialog auf
**Ja** klicken. Der Assistent erkennt, dass nur noch Schritt 8 offen ist,
und macht weiter.

### „UDEF-Key konnte nicht angelegt werden“

Heißt meist: Der Oracle-Benutzer hat keine `INSERT`-Rechte auf die
Tabelle `WUSS`. Der Assistent zeigt in diesem Fall das passende
`INSERT`-SQL – das kann der DBA zusammen mit dem Trigger-SQL aus
Schritt 6 ausführen.

### Passwort des Verwalters vergessen

Ein anderer Verwalter setzt unter **Benutzer** ein neues Startpasswort. Gibt es
keinen anderen Verwalter: **am Server selbst** (direkt oder per Remotedesktop)
`slim\reset_admin.cmd` doppelklicken, beim UAC-Dialog „Ja“.

- Das Skript zeigt die vorhandenen Benutzer und fragt nach dem Namen und einem
  neuen Startpasswort (mind. 10 Zeichen, zweimal eingeben).
- Ein vorhandener Verwalter bekommt das neue Startpasswort, ein Benutzer mit
  „ansehen“ wird zusätzlich Verwalter, ein unbekannter Name wird als neuer
  Verwalter angelegt.
- Bei der nächsten Anmeldung muss das Passwort geändert werden. Alle anderen
  Benutzer bleiben unverändert, der Vorgang steht im Protokoll
  (`admin_zurueckgesetzt`). Ein Dienst-Neustart ist nicht nötig – nur wenn die
  Anmeldung nach Fehlversuchen gesperrt ist (sonst 15 Minuten warten).

Das Zurücksetzen gibt es bewusst nur am Server: keine Funktion in der
Oberfläche, und über eine Netzwerkfreigabe (`\\server\...`) gestartet bricht
das Skript ab.

Ist die Datei `slim\data\users.json` beschädigt: Datei umbenennen, Dienst neu
starten und am Server unter `http://127.0.0.1:8022/` den ersten Verwalter neu
anlegen.

### Setup nochmal starten

Wenn etwas grundlegend schiefging und Sie von vorne anfangen wollen:
die Datei `slim\config\.setup_done` löschen und `setup_slim.cmd` neu
starten. Vorhandene Benutzer bleiben erhalten.

---

## Was die App im Anschluss tut

Alle 30 Sekunden (einstellbar):

1. Liest in Suite8 die wartenden Folio-Mails (mit `BLOCKSEND=1`)
2. Liest aus Betreff / Dateiname die Rechnungsnummer per Pattern
3. Holt die Rechnungsdaten aus Suite8 (Adresse, Gast und Zimmer je Buchung)
4. Erzeugt das XRechnung-XML (Format 3.0, KoSIT-geprüft)
5. Speichert das XML lokal unter `slim\data\xml\YYYY\MM\<Nummer>.xml`
6. Hängt das XML an die Suite8-Mail als zweiten Anhang (bei Nur-XML: nimmt
   PDF und RTF aus der Mail)
7. Setzt `WMAI_BLOCKSEND=0` – Suite8 verschickt die Mail jetzt

Bei Problemen (Validierung schlägt fehl, KoSIT meldet Fehler …) bleibt
die Mail in Suite8 stehen und auf der Startseite taucht eine Zeile mit
„Neu versuchen“-Knopf auf. Klick auf den Knopf → der nächste Poll-Lauf
probiert es erneut.

Die `WMAI_ERROR`-Spalte in Suite8 zeigt den Fehlertext auch in der
Suite8-Oberfläche – der Front-Office-Mitarbeiter sieht also direkt in Suite8,
warum die Mail hängt.
