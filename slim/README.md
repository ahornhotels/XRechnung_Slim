# Suite8 XRechnung Slim

Standalone-Variante der Suite8 XRechnung MiniApp: schlanker Hintergrund-Poller, der XRechnung-XML an in Suite8 vorbereitete Folio-Mails (WMAI mit `BLOCKSEND=1`) anhaengt. Kein Login, keine DB, kein Mail-Versand durch die App.

## Architektur in einem Satz

Ein zweiter NSSM-Service (`Suite8XRechnungSlim`, Port 8022) auf demselben Host wie die Vollversion, teilt sich den Code-Stack (`modules/`, `templates/`, `validation/`, `install/jre/`) und nutzt eine **eigene Konfiguration** unter `slim/config/`.

## Was es macht

1. Alle `suite8_poll_interval_seconds` (Default 30s) sucht der Poller WMAI-Eintraege mit `BLOCKSEND=1 AND SENT=0`.
2. Aus Filename / Subject wird die ZINV-Nummer extrahiert (Regex aus `hotel.json`).
3. Rechnung wird aus Suite8 gefetched, validiert (eigener + KoSIT), als UBL XRechnung 3.0 gebaut.
4. XML landet **im Filesystem** unter `slim/data/xml/YYYY/MM/<zinv>.xml` + `<zinv>.sha256`.
5. XML wird per `WMAA`-Insert + WTXT-BLOB an die WMAI gehaengt, `WMAI_BLOCKSEND=0` (Suite8-Mailservice nimmt sie sich).
6. Audit-Eintrag in `slim/data/audit-YYYY-MM.jsonl`.

Bei Fehlern wird `WMAI_ERROR` auf die Fehlermeldung gesetzt (sichtbar in der Suite8-UI), ein JSONL-Eintrag geschrieben, und der Eintrag bleibt im UI als "Retry"-faehig stehen.

## Was es NICHT macht

- **Kein Versand**: der Suite8-Mailservice sendet die Mail. Diese App attached nur.
- **Kein Auth**: bind nur `127.0.0.1`. Wer auf den Server kommt, sieht das UI.
- **Keine DB-Persistenz**: alles im Filesystem.
- **Kein Auto-Update**: per `git pull` + Service-Restart aktualisieren.

## Setup

```cmd
:: 1. Configs anlegen
copy slim\config\hotel.json.example   slim\config\hotel.json
copy slim\config\connection.json.example slim\config\connection.json
copy slim\config\app_settings.json.example slim\config\app_settings.json
:: hotel.json und connection.json mit echten Werten editieren

:: 2. Oracle-Passwort verschluesseln (interaktiver Prompt, kein History-Leak)
install\python\python.exe slim\scripts\set_password.py

:: 3. Service installieren (NSSM, Port 8022, AutoStart)
slim\install\install_slim.cmd
```

Audit-Dateien rotieren nach **UTC**-Monatswechsel — wer auf MEZ schaut,
sieht den Wechsel evtl. eine Stunde verzoegert.

## Pattern-Konfiguration (kritisch pro Hotel)

Jedes Haus nutzt einen anderen Mail-Template — die ZINV-Nummer kann
im Subject oder im Filename stehen. **Beide Patterns sind im UI
editierbar** (Sektion "Pattern-Konfiguration"). Default: Subject mit
``Rechnung Nr. <ZINV_NUMBER>``.

**Wichtig:** Suite8 schreibt im PDF-Filename die ``ZINV_ID`` (interner
DB-Primaerschluessel), NICHT die ``ZINV_NUMBER`` (die externe
Rechnungs-Folio-Nummer). Wer den Filename als Quelle nutzt, muss
sicherstellen, dass die extrahierte Zahl wirklich die ZINV_NUMBER
ist — bei manchen Suite8-Konfigurationen ist das nicht der Fall, daher
hier das Default-Pattern auf den Subject gestellt.

UI-Workflow:
1. Subject-Pattern eintragen mit Named-Group ``(?P<zinv_number>\d+)``
2. Im "Pattern testen"-Block ein Beispiel-Subject eingeben
3. Wenn das UI ``Match: zinv_number=XXXXX (aus subject)`` meldet → Speichern
4. Server-Restart **nicht** noetig — wirkt im naechsten Poll-Lauf

Danach: <http://127.0.0.1:8022/>

## Pfad-Layout

```
slim/
├── main_slim.py            FastAPI-Entry
├── core_slim/              Audit JSONL + XML-Archiv
├── jobs_slim/poller.py     Poller-Loop (analog jobs/suite8_attach_poller.py)
├── api_slim/               /api/status, /api/pending, /api/audit/tail, /api/wmai/{id}/retry
├── frontend/index.html     Single-Page UI
├── config/                 hotel.json, connection.json, app_settings.json, connection.key
├── data/
│   ├── audit-YYYY-MM.jsonl Audit-Log (rotierend monatlich)
│   └── xml/YYYY/MM/        XRechnung-XML + SHA256 + optional KoSIT-Report
├── install/install_slim.cmd
├── scripts/set_password.py
└── logs/                   NSSM-Stdout/Stderr
```

## Audit-Events

| Event | Wann |
|---|---|
| `pattern_no_match` | Regex hat in Filename/Subject keine ZINV gefunden |
| `pattern_ambiguous` | Filename und Subject liefern unterschiedliche ZINV |
| `zinv_not_found` | ZINV-Nummer nicht in Suite8 DB |
| `validator_fail` | Eigener Pflichtfeld-Validator hat Issues |
| `xml_build_fail` | UBL-Schema-Verletzung |
| `kosit_fail` | KoSIT-CLI hat das XML abgelehnt (oder KoSIT nicht installiert) |
| `attach_fail` | Anhaengen an WMAI fehlgeschlagen (DB-Race o.ae.) |
| `attach_ok` | XML erzeugt, archiviert, an WMAI gehaengt |
| `retry_triggered` | User hat im UI "Neu versuchen" gedrueckt |
| `poller_crash` | Unerwartete Exception im Poller-Loop |

**Spam-Schutz**: identischer Fehler fuer dieselbe WMAI loggt nur einmal — der Audit-Schreiber liest erst `WMAI_ERROR`, vergleicht mit neuem Text und ueberspringt das Schreiben wenn unveraendert.

## Tests

```cmd
install\python\python.exe -m pytest tests_slim -q
```
