# Slim-App installieren

Drei Schritte. Mehr nicht.

## Voraussetzungen

- **Windows 10, Windows 11 oder Windows Server 2019/2022** (jeweils x64).
  Für Test und Demo reicht Windows 11; für produktiven Dauerbetrieb ist
  ein Server-OS empfohlen.
- Oracle-Zugangsdaten (TNS-Alias, Benutzername, Passwort) von Ihrer IT.
- Sie sind als Benutzer mit **Administrator-Rechten** angemeldet.

**Hinweis Win 10/11:** Der Slim-Dienst läuft auch nach Benutzer-Abmeldung
weiter — Windows-Dienste sind von User-Sessions unabhängig. Aber wenn
der Rechner in Standby/Hibernate geht, pausiert auch der Dienst. Vor
Dauereinsatz im Energie-Plan unter *Energieoptionen* die Standby-Zeit
auf "Nie" stellen.

**Hinweis Big-App:** Wenn die Vollversion bereits unter
`C:\FIDELIO\Suite8XRechnung` installiert ist, kann die Slim deren
Python/JRE/NSSM mitbenutzen. Ist sie nicht installiert, bringt das
mitgelieferte ZIP alles selbst mit.

## Schritt 1 - Setup-Assistent starten

Im Explorer in den Ordner `slim` wechseln und auf

```
setup_slim.cmd
```

**doppelklicken**.

Es kommt ein UAC-Dialog ("Moechten Sie zulassen ..." → **Ja**).
Danach oeffnet sich:

- ein schwarzes Fenster (das ist der Server — bitte offen lassen)
- der Browser mit dem Setup-Assistenten

## Schritt 2 - Den Assistenten durchklicken

Der Assistent fragt in 7 Schritten alles Noetige ab:

1. **Willkommen** — kurze Erklaerung
2. **Datenbank** — Sie tragen TNS-Alias, Benutzername und Passwort
   ein. Knopf "Verbindung testen" — wenn gruen, klicken Sie auf
   "Weiter →"
3. **Stammdaten** — der Assistent zeigt, welche Hotel-Werte schon in
   Suite8 gepflegt sind. Wenn welche fehlen: in Suite8 nachpflegen,
   "Erneut pruefen". Sonst weiter
4. **UDEF-Keys** — die drei XRechnung-Werte. Defaults sind sinnvoll
   ("14" Tage, "Buchhaltung"). Knopf "In Suite8 anlegen" → der Assistent
   schreibt die Werte direkt in Suite8
5. **Pattern** — der Standard ist meist richtig
   (`Rechnung Nr. <Nummer>`). Kopieren Sie einen echten Mail-Betreff
   aus Suite8 in das Test-Feld, dann "Pattern jetzt testen". Wenn der
   Treffer gruen ist: "Pattern speichern"
6. **SQL fuer Datenbank-Administrator** — der Assistent zeigt ein
   fertiges SQL. Knopf "In Zwischenablage kopieren" → das SQL Ihrem
   Suite8-DBA per Mail oder Ticket senden. Der DBA fuehrt es einmal aus
7. **Hotel** — Hotel-Code, Name, Adresse, Ansprechpartner
   Buchhaltung. "Speichern"
8. **Fertig** — Knopf "Service installieren und starten". Der Assistent
   meldet "Service wurde installiert und gestartet"

## Schritt 3 - Fertig

Klicken Sie auf "Zur Status-Seite". Das ist die Hauptansicht der App:
zeigt Polling-Statistik, wartende Suite8-Mails und das Audit-Log.

Die App laeuft jetzt als Windows-Dienst und startet bei jedem Server-Neustart
automatisch. Sie ist unter `http://127.0.0.1:8022/` erreichbar.

---

## Wenn etwas schief geht

### "Verbindung fehlgeschlagen" in Schritt 2

Die Slim-App liefert das Oracle-Client-Material mit (Thick-Mode-Default),
daher sind die haeufigsten Probleme:

| Fehlertext | Bedeutung | Loesung |
|---|---|---|
| `ORA-12154: TNS:could not resolve...` | TNS-Alias nicht in `tnsnames.ora` gefunden | **Easy Connect verwenden** im Feld "TNS-Alias": `<db-host>:1521/<SERVICE_NAME>`, das TNS-Admin-Feld leer lassen |
| `ORA-01017: invalid username/password` | Zugangsdaten falsch | Username + Passwort mit dem DBA klaeren |
| `ORA-12541: no listener` | DB-Server-Listener nicht erreichbar | Host, Port, Firewall pruefen |
| `ORA-12170: Connect timeout` | Netzwerk-Problem | VPN, Routing, Firewall pruefen |

Bei Verdacht auf TNS-Probleme das Diagnose-Skript ausfuehren — es zeigt
Pfade, gefundene Aliase und macht einen Connect-Versuch:
```cmd
install\python\python.exe scripts\diagnose_tns.py
```

**Drei Eingabe-Varianten im "TNS-Alias"-Feld sind erlaubt:**

a) **TNS-Alias** aus der `tnsnames.ora` — z.B. `V8`
   *plus* TNS-Admin-Pfad mit dem Verzeichnis, in dem `tnsnames.ora` liegt
   (oder leer fuer Auto-Suche in den ueblichen Oracle-Client-Pfaden)

b) **Easy Connect** ★ am robustesten *plus* TNS-Admin leer lassen
   ```
   db-host:1521/SERVICE_NAME
   ```

c) **Voller Connect-String**, z.B. fuer 21c-PDB-Setups *plus* TNS-Admin leer
   ```
   (DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=...)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=...)))
   ```

Den Service-Namen liefert der DBA per:
```sql
SELECT VALUE FROM V$PARAMETER WHERE NAME = 'service_names';
```

### "Service-Installation nicht durchgekommen" in Schritt 8

Heisst meist: der Setup-Assistent lief nicht als Administrator. Loesung:
ein zweites Mal auf `setup_slim.cmd` doppelklicken — beim UAC-Dialog auf
**Ja** klicken — der Wizard erkennt, dass nur noch Schritt 8 offen ist,
und macht weiter.

### "UDEF-Key konnte nicht angelegt werden"

Heisst meist: der Oracle-Benutzer hat keine `INSERT`-Rechte auf die
Tabelle `WUSS`. Der Wizard zeigt in diesem Fall das passende
`INSERT`-SQL — das kann der DBA zusammen mit dem Trigger-SQL aus
Schritt 6 ausfuehren.

### Setup nochmal starten

Wenn etwas grundlegend schief ging und Sie von vorne anfangen wollen:
die Datei `slim\config\.setup_done` loeschen und `setup_slim.cmd` neu
starten.

---

## Was die App im Anschluss tut

Alle 30 Sekunden (konfigurierbar):

1. Liest in Suite8 die wartenden Folio-Mails (mit `BLOCKSEND=1`)
2. Liest aus Subject / Filename die Rechnungsnummer per Pattern
3. Holt die Rechnungsdaten aus Suite8
4. Erzeugt das XRechnung-XML (Format 3.0, KoSIT-validiert)
5. Speichert das XML lokal unter `slim\data\xml\YYYY\MM\<Nummer>.xml`
6. Haengt das XML an die Suite8-Mail als zweiten Anhang
7. Setzt `WMAI_BLOCKSEND=0` — Suite8 verschickt die Mail jetzt

Bei Problemen (Validierung schlaegt fehl, KoSIT meckert, ...) bleibt
die Mail in Suite8 stehen und im Slim-UI taucht eine Zeile mit
"Neu versuchen"-Knopf auf. Klick auf den Knopf → naechster Poll-Lauf
probiert es erneut.

Die `WMAI_ERROR`-Spalte in Suite8 zeigt den Fehlertext auch in der
Suite8-UI — der Front-Office-Mitarbeiter sieht also direkt in Suite8,
warum die Mail haengt.
