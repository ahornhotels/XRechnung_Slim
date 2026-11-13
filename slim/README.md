# Suite8 XRechnung Slim

Standalone-Variante der Suite8 XRechnung MiniApp: schlanker Hintergrund-Poller, der XRechnung-XML an in Suite8 vorbereitete Folio-Mails (WMAI mit `BLOCKSEND=1`) anhängt. Mit Anmeldung (Rollen „ansehen“ und „verwalten“) und allen Einstellungen in der Oberfläche, ohne eigene DB, kein Mail-Versand durch die App.

Installation und Bedienung: [INSTALL.md](INSTALL.md) · Vorab lesen: [README_FIRST.md](README_FIRST.md)

## Architektur in einem Satz

Ein eigenständiger NSSM-Service (`Suite8XRechnungSlim`, Port 8022). Bringt seinen kompletten Code-Stack (`modules/`, `templates/`, `sql/`, `validation/`, `install/`) selbst mit (vendored) und nutzt eine **eigene Konfiguration** unter `slim/config/`. Eine Big-App-Installation ist nicht erforderlich.

## Was es macht

1. Alle `suite8_poll_interval_seconds` (Standard 30 s) sucht der Poller WMAI-Einträge mit `BLOCKSEND=1 AND SENT=0`.
2. Aus Dateiname / Betreff wird die ZINV-Nummer extrahiert (Regex, einstellbar).
3. Die Rechnung wird aus Suite8 gelesen und angereichert:
   - Käuferadresse aus genau einer Suite8-Adresse (Straße 1–3, leere Zeilen fallen weg),
   - Gast und Zimmer je Buchung (`ZPOS_ORIGINATED_*`, Zimmer aus `YDET` am Buchungstag),
   - gleiche Buchungen zusammengefasst, bei Gruppenrechnungen Zimmer/Gast je Position (BT-127, BT-134/135),
   - bei genau einem Gast Gastzeile im Hinweis (BT-22) und Lieferempfänger (BT-70),
   - Auslage-Artikel und Paid-Out ohne Steuerbuchung mit 0 %.
4. Sie wird geprüft (eigener Validator + KoSIT) und als UBL XRechnung 3.0 gebaut (Rechnung 380 bzw. Gutschrift 381).
5. Das XML landet **im Dateisystem** unter `slim/data/xml/YYYY/MM/<zinv>.xml` + `<zinv>.sha256`.
6. Das XML wird per `WMAA`-Insert + WTXT-BLOB an die WMAI gehängt, `WMAI_BLOCKSEND=0` (der Suite8-Mailservice nimmt sie sich). Bei **Nur-XML** (Membership „PDF“ des Rechnungsempfängers oder Schalter „Nur XML für alle“) werden in derselben Transaktion PDF- und RTF-Anhang aus der WMAI genommen – gelöscht wird nichts.
7. Audit-Eintrag in `slim/data/audit-YYYY-MM.jsonl`.

Bei Fehlern wird `WMAI_ERROR` auf die Fehlermeldung gesetzt (sichtbar in der Suite8-Oberfläche), ein JSONL-Eintrag geschrieben, und der Eintrag bleibt in der Oberfläche als „Neu versuchen“-fähig stehen.

## Anmeldung

- Benutzer mit den Rollen „ansehen“ (nur lesen) und „verwalten“ (Einstellungen, Benutzer, Overrides, Neu versuchen, Updates) in `slim/data/users.json`, Passwörter nur als PBKDF2-Hash.
- Den ersten Verwalter legt man **am Server selbst** unter `http://127.0.0.1:8022/login` an – nur solange es keinen Benutzer gibt. Bis dahin läuft der Rechnungsversand normal weiter.
- Sitzung 8 Stunden, Cookie `HttpOnly`/`SameSite=Strict`. Startpasswörter müssen bei der ersten Anmeldung geändert werden.
- Fehlversuche: von anderen Rechnern 15 Minuten Sperre nach 5 Fehlversuchen; am Server keine Sperre, aber höchstens ein Versuch pro Sekunde und Benutzer, ab dem 5. Fehlversuch wachsende Wartezeit (bis 60 s).
- Standard-Bind `127.0.0.1`. Für LAN-Zugriff unter *Einstellungen → Server* die Adresse `0.0.0.0` und die erlaubten Adressen (IPs oder Netze wie `192.168.10.0/24`) setzen, danach neu starten. localhost ist immer erlaubt.

## Einstellungen

Alles aus `connection.json`, `hotel.json`, `app_settings.json` und `update.json` ist unter `/settings` änderbar, nur mit der Rolle „verwalten“. Vor jedem Speichern entsteht eine Sicherung `<datei>.<zeitstempel>.sicherung` (die letzten 20 bleiben). Passwort und Token werden verschlüsselt gespeichert und nie angezeigt. Verkäuferdaten kommen aus Suite8 und können abweichend gesetzt werden (`seller_overrides` in `hotel.json`). Slim schreibt außerhalb des Setup-Assistenten nie nach WUSS.

Wichtige Schalter in `hotel.json` (Standardwerte in `config/hotel.json.example`):

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `gastzeile` | `Gast: {gast}, Zimmer {zimmer}, {anreise} bis {abreise}` | Hinweis bei genau einem Gast; leer = aus |
| `positionen_zusammenfassen` | `true` | gleiche Buchungen als eine Position mit Menge |
| `auslagen_artikel` | `["AUS", "DUR"]` | Artikel-Kurznamen, die ohne Steuerbuchung mit 0 % gelten |
| `xml_only_membership` | `PDF` | Membership-Kurzbezeichnung für Nur-XML; leer = aus |
| `xml_only_all` | `false` | Nur-XML für alle Rechnungen |
| `rundungsausgleich` | `aus` | `position` oder `abschlag`: Steuer je Satz vom Brutto neu (Bemessung = Positionen exakt, für strenge Empfänger wie SAP); Rest in der größten Position bzw. als Abschlag/Zuschlag „Rundungsausgleich“. Endbetrag bleibt gleich |

## Was es NICHT macht

- **Kein Versand**: Der Suite8-Mailservice sendet die Mail. Diese App hängt nur an.
- **Keine DB-Persistenz**: alles im Dateisystem.

## Setup

Normalerweise über den Setup-Assistenten (`slim\setup_slim.cmd`, siehe [INSTALL.md](INSTALL.md)). Manuell ohne Assistent:

```cmd
:: 1. Configs anlegen
copy slim\config\hotel.json.example      slim\config\hotel.json
copy slim\config\connection.json.example slim\config\connection.json
copy slim\config\app_settings.json.example slim\config\app_settings.json
:: hotel.json und connection.json mit echten Werten editieren

:: 2. Oracle-Passwort verschlüsseln (interaktiver Prompt, kein History-Leak)
install\python\python.exe slim\scripts\set_password.py

:: 3. Service installieren (NSSM, Port 8022, AutoStart)
slim\install\install_slim.cmd

:: 4. Am Server http://127.0.0.1:8022/login öffnen und ersten Verwalter anlegen
```

Audit-Dateien rotieren nach **UTC**-Monatswechsel – wer auf MEZ schaut,
sieht den Wechsel evtl. eine Stunde verzögert.

## Pattern-Konfiguration (kritisch pro Hotel)

Jedes Haus nutzt ein anderes Mail-Template – die ZINV-Nummer kann
im Betreff oder im Dateinamen stehen. **Beide Patterns sind in der Oberfläche
editierbar** (Startseite, Abschnitt „Pattern-Konfiguration“, oder
*Einstellungen → Versand*). Standard: Betreff mit
`Rechnung Nr. <ZINV_NUMBER>`.

**Wichtig:** Suite8 schreibt in den PDF-Dateinamen die `ZINV_ID` (interner
DB-Primärschlüssel), NICHT die `ZINV_NUMBER` (die externe
Rechnungsnummer). Wer den Dateinamen als Quelle nutzt, muss
sicherstellen, dass die extrahierte Zahl wirklich die ZINV_NUMBER
ist – oder die Gruppe `(?P<zinv_id>...)` verwenden. Deshalb steht das
Standard-Pattern auf dem Betreff.

Ablauf in der Oberfläche:
1. Betreff-Pattern eintragen mit der Named-Group `(?P<zinv_number>\d+)`
2. Im Block „Pattern testen“ ein Beispiel-Betreff eingeben
3. Wenn die Oberfläche `Match: zinv_number=XXXXX (aus subject)` meldet → Speichern
4. Server-Neustart **nicht** nötig – wirkt im nächsten Poll-Lauf

## Pfad-Layout

```
slim/
├── main_slim.py            FastAPI-Einstieg (Middleware: IP-Filter, Anmeldung)
├── core_slim/              Audit JSONL, XML-Archiv, Benutzer/Sitzungen (auth.py),
│                           Einstellungsschema, Overrides, Updater
├── jobs_slim/poller.py     Poller-Schleife
├── api_slim/               /api/status, /api/pending, /api/audit/tail, /api/wmai/{id}/retry,
│                           /api/auth/*, /api/users, /api/settings, /api/system/restart, /api/archive
├── frontend/               index.html (Startseite), login.html, users.html,
│                           settings.html, setup.html (Assistent)
├── config/                 hotel.json, connection.json, app_settings.json, update.json, connection.key
├── data/
│   ├── users.json          Benutzer (Passwort-Hashes)
│   ├── overrides/          Overrides je WMAI
│   ├── audit-YYYY-MM.jsonl Audit-Log (rotiert monatlich)
│   └── xml/YYYY/MM/        XRechnung-XML + SHA256 + optional KoSIT-Report
├── install/                install_slim.cmd, uninstall_slim.cmd
├── scripts/                set_password.py, setup_suite8.py
└── logs/                   NSSM-Stdout/Stderr
```

## Audit-Events

| Event | Wann |
|---|---|
| `pattern_no_match` | Regex hat in Dateiname/Betreff keine ZINV gefunden |
| `pattern_ambiguous` | Dateiname und Betreff liefern unterschiedliche ZINV |
| `zinv_not_found` | ZINV-Nummer nicht in der Suite8-DB |
| `validator_fail` | Eigener Pflichtfeld-Validator hat Befunde |
| `xml_build_fail` | UBL-Schema-Verletzung |
| `kosit_fail` | KoSIT-CLI hat das XML abgelehnt (oder KoSIT nicht installiert) |
| `attach_fail` | Anhängen an WMAI fehlgeschlagen (DB-Race o. Ä.) |
| `attach_ok` | XML erzeugt, archiviert, an WMAI gehängt (bei Nur-XML mit `xml_only`, `pdf_removed`) |
| `retry_triggered` | Benutzer hat „Neu versuchen“ gedrückt |
| `poller_crash` | Unerwartete Exception in der Poller-Schleife |
| `login_ok` / `login_failed` / `login_blocked` / `login_throttled` / `logout` | Anmeldung |
| `bootstrap_admin` | Erster Verwalter angelegt |
| `user_created` / `user_changed` / `user_deleted` / `password_changed` | Benutzerverwaltung |
| `settings_changed` | Einstellungen gespeichert (welche Schlüssel, ohne Werte) |

**Spam-Schutz**: Ein identischer Fehler für dieselbe WMAI wird nur einmal protokolliert – der Audit-Schreiber liest erst `WMAI_ERROR`, vergleicht mit dem neuen Text und überspringt das Schreiben, wenn er unverändert ist.

## Tests

```cmd
install\python\python.exe -m pytest tests_slim -q
```
