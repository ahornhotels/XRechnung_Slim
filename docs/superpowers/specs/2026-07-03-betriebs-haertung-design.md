# Design-Spec: Betriebs-Härtung (3 Punkte)

Datum: 2026-07-03 · Projekt: XRechnung_Slim · Status: freigegeben (Brainstorming)

## Überblick

Drei unabhängige, betriebsnahe Verbesserungen, gebündelt als ein Wartungs-Batch.
Jeder Punkt ist einzeln implementier- und testbar:

1. **BillingReference-Fallback** — Gutschrift (381) ohne `ZINV_VOID_ZINV_ID` erhält
   ihren Original-Rechnungsbezug aus dem Zahlungs-Kommentar (`ZPOS_COMMENT`).
2. **IP-Allowlist** — die App wird per Netzwerk-IP erreichbar, Zugriff aber auf
   konfigurierbare IPs/CIDR-Ranges beschränkt (localhost immer erlaubt).
3. **Log-Zeit → PC-Zeit** — Audit- und Archiv-Zeitstempel von UTC auf lokale
   Server-Zeit (offset-aware) umstellen.

Bewusst **nicht** im Umfang (YAGNI): UI-Editor für App-Settings, Reverse-Proxy-/
X-Forwarded-Unterstützung, Änderungen an `logs/app.log` (nutzt bereits Lokalzeit),
Änderung der Zahlungsrichtung/IBAN bei Gutschriften.

---

## Punkt 1 — BillingReference-Fallback (Variante C)

### Problem
Eine XRechnung-Gutschrift (`InvoiceTypeCode = 381`) benötigt zwingend den Bezug zur
Original-Rechnung (BG-3, `cac:BillingReference`). Heute wird `BillingReferenceID`
ausschließlich aus `ZINV.ZINV_VOID_ZINV_ID` abgeleitet (`sql/invoice_header.sql`).
Legt der Operator die Storno-/Gutschrift-Rechnung in Suite8 **ohne** diesen Bezug an,
bleibt das Feld leer und der Validator (`invoice_validator.py`) blockt mit BG-3.

In der Hotel-Praxis trägt der Operator die Original-Rechnungsnummer stattdessen als
Freitext in den **Kommentar der Zahlungszeile** ein.

### Lösung (Hybrid: SQL liefert Rohwert, Python macht die Logik)

**SQL — `sql/invoice_header.sql`:** eine neue Spalte, die das bestehende
`PaymentMeansCode`-Muster (Zeile 83) spiegelt — `ZPOS_COMMENT` der Zahlungszeile mit
`max(zpos_id)` und `zpos_cdt=5` der Rechnung:

```sql
(select Z1.zpos_comment from zpos Z1
   where Z1.zpos_id = (select max(Z2.zpos_id) from zpos Z2, zpil I2
                       where Z2.zpos_id = I2.zpil_zpos_id
                         and Z2.zpos_cdt = 5
                         and I2.zpil_zinv_id = zinv_id)) PaymentRefComment,
```

Hinweis: Feld heißt real `ZPOS_CDT` (nicht `zpos_zdt`); `CDT=5` = Zahlungszeile.

**Python — `modules/invoice_fetcher.py`:** direkt nach dem bestehenden Block
`if is_credit_note(...): header["invoicetypecode"] = "381"` ein Fallback, der **nur**
greift, wenn TypeCode `381` **und** `billingreferenceid` leer ist:

- reine, testbare Funktion `_extract_number_candidates(comment: str) -> list[str]`:
  alle zusammenhängenden Ziffernfolgen aus dem Freitext, **längste zuerst**
  (Tie-Break gegen Streuzahlen wie Jahreszahlen). Beispiel:
  `"Storno zu RG 12345"` → `["12345"]`; `"2024-987"` → `["2024", "987"]`.
- Validierung über den **bereits offenen Cursor** (keine neue Connection):
  `SELECT zinv_number, TO_CHAR(zinv_date,'YYYY-MM-DD') FROM zinv WHERE zinv_number = :nr`
  je Kandidat; **erster Treffer gewinnt**.
- Treffer → `header["billingreferenceid"]` **und** `header["billingreferenceissuedate"]`
  (letzteres füllt das optionale Feld im CreditNote-Template).
- Kein Treffer / kein Kommentar / keine Zahlungszeile → Feld bleibt leer → der
  bestehende Validator meldet weiterhin den BG-3-Fehlbezug. **Kein stiller Fake-Bezug.**

### Datenfluss
```
fetch_invoice()
  → header (billingreferenceid evtl. leer, PaymentRefComment gesetzt)
  → is_credit_note() == True → typecode 381
  → billingreferenceid leer? → _resolve_billing_reference_from_payment(cur, header)
       → _extract_number_candidates(PaymentRefComment)
       → je Kandidat ZINV-Lookup → erster Treffer setzt id + issuedate
```

### Tests (`tests_slim/`)
- `_extract_number_candidates`: reiner Text — leer, nur Ziffern, eingebettet,
  mehrere Folgen (Reihenfolge längste-zuerst), keine Ziffern.
- Fallback mit gemocktem Cursor: Treffer / kein Treffer / leerer Kommentar /
  mehrere Kandidaten (erster gültiger gewinnt) / bereits gesetzte `billingreferenceid`
  (Fallback greift nicht).

### Randfälle
- `ZPOS_COMMENT` NULL / keine Zahlungszeile → `PaymentRefComment` None → übersprungen.
- Kommentar enthält keine Ziffern → keine Kandidaten → Feld leer.
- Kandidat existiert nicht als `zinv_number` → nächster Kandidat, sonst leer.
- Bestehender `ZINV_VOID_ZINV_ID`-Bezug hat Vorrang (Fallback nur bei leerem Feld).

---

## Punkt 2 — IP-Allowlist (Netzwerk-Zugriff)

### Problem
Die App bindet heute auf `127.0.0.1` (`main_slim.py:171`, Default aus `app_settings.json`)
und hat **keine Authentifizierung** (`slim/README.md:23` nennt die localhost-Bindung
ausdrücklich als Sicherheitsgrenze). Gewünscht ist Erreichbarkeit per Netzwerk-IP,
aber beschränkt auf konfigurierbare Adressen.

### Lösung (Zugriffs-Allowlist als Middleware)
Nicht die Bindung feinsteuern, sondern eine Allowlist über eine HTTP-Middleware —
localhost immer erlaubt.

**Konfig — `app_settings.json` / `app_settings.json.example`:** neuer Key
```json
"allowed_ips": []
```
Einträge: exakte IPv4/IPv6-Adressen **oder** CIDR-Ranges (z. B. `"192.168.10.0/24"`).
`127.0.0.1` und `::1` sind **immer** erlaubt, unabhängig von der Liste. Leere Liste
+ `host: "0.0.0.0"` ⇒ effektiv nur localhost (sicherer Default).

**Bindung:** Für LAN-Erreichbarkeit muss `"host"` auf `"0.0.0.0"` gesetzt werden;
Default in `.example` bleibt sicherheitshalber `"127.0.0.1"`. Die Allowlist ist die
eigentliche Zugriffskontrolle.

**Reine Funktion — neu `slim/core_slim/access.py`:**
```
def is_ip_allowed(client_ip: str, allowed: list[str]) -> bool
```
- localhost (`127.0.0.1`, `::1`) → immer `True`.
- sonst: `client_ip` gegen jeden Eintrag via `ipaddress` prüfen
  (exakte Adresse **oder** `ip in ip_network(entry)`).
- ungültige/leere Einträge werden übersprungen (defensiv, kein Crash).

**Middleware — `main_slim.py`** (registriert **vor** den Routern):
- liest `allowed_ips` **beim Start** in den App-State (Konfig-Änderung ⇒ Dienst-Neustart,
  konsistent mit `host`/`port`).
- prüft `request.client.host` via `is_ip_allowed`.
- nicht erlaubt → **HTTP 403** JSON `{"detail": "Zugriff von <ip> nicht erlaubt"}`
  + `logger.warning`.
- kein Reverse-Proxy im Setup → `request.client.host` ist die echte Peer-IP.

**Doku:** Key in `app_settings.json.example` ergänzen und in `slim/README.md` /
`INSTALL.md` beschreiben (inkl. Sicherheitshinweis: LAN-Exposition ohne Login).

### Tests (`tests_slim/`)
- `is_ip_allowed`: localhost immer erlaubt; exakte IP-Treffer/Fehltreffer;
  CIDR-Range-Treffer/Fehltreffer; leere Liste; ungültige Einträge werden ignoriert;
  IPv6-localhost.
- Middleware-Verdrahtung leichtgewichtig (erlaubte vs. geblockte IP), soweit mit
  FastAPI-`TestClient` sinnvoll simulierbar.

### Randfälle
- `request.client` None (theoretisch) → als nicht-localhost behandeln → 403.
- IPv6-Mapped-IPv4 → über `ipaddress` normalisieren.
- Konfig fehlt/leer → nur localhost erlaubt (fail-safe).

---

## Punkt 3 — Log-Zeit → PC-Zeit (lokal)

### Problem
Audit- und Archiv-Zeitstempel stehen auf UTC, während der Server auf UTC+2 (MESZ)
läuft — der Operator sieht „GMT" statt PC-Zeit. `logs/app.log` ist bereits lokal
(Formatter-Default `time.localtime`) und bleibt unverändert.

Betroffen (bewusst UTC gesetzt):
- `slim/core_slim/audit_jsonl.py` — `_now_iso()` (`…Z`), `_audit_path`, `tail`.
- `slim/core_slim/archive_fs.py` — `_bucket` (`xml/JJJJ/MM`), Versions-Zeitstempel.

### Lösung
**Ein Helper — neu `slim/core_slim/clock.py`:**
```
def now_local() -> datetime:
    return datetime.now().astimezone()   # offset-aware, lokale Zeitzone
```

**`audit_jsonl.py`:**
- `_now_iso()` formatiert `now_local()` als ISO8601 mit Millisekunden **und Offset**,
  z. B. `2026-07-03T11:54:48.123+02:00` (zeigt PC-Zeit, bleibt eindeutig/parsebar).
- `_audit_path`, `tail` Default-`now` → `now_local()`; Monatsdatei folgt lokalem Monat.

**`archive_fs.py`:**
- `_bucket` und Versions-Zeitstempel (`.YYYYmmddTHHMMSS.xml`) Default-`now` → `now_local()`.

**Konsistenz-Mitnahme (Status-UI zeigt ebenfalls PC-Zeit):**
- `main_slim.py` `state["last_run"]`
- `slim/api_slim/run_now.py` `started_at`
- `slim/core_slim/updater.py` `applied_at`
→ jeweils `now_local().isoformat()` statt `datetime.now(timezone.utc)`.

### Tradeoff (bewusst akzeptiert)
Audit/Archiv rotieren jetzt nach **lokalem** Monatswechsel statt UTC. Ein Eintrag um
00:30 MESZ am Monatsersten landet nun im neuen Monat (vorher im UTC-Vormonat).
Intuitiver für den Operator; Format bleibt maschinenlesbar (Offset erhalten).

### Tests (`tests_slim/`)
- `test_audit_jsonl.py`: `ts`-Format (Offset statt `Z`), Monatsrouting mit
  lokal-aware `now`, `tail` über Monatsgrenze.
- `test_archive_fs.py`: Bucket-/Versions-Zeitstempel mit lokal-aware `now`.
- `now`-Injection-Muster bleibt überall erhalten (Tests übergeben aware-`datetime`).

---

## Betroffene Dateien (Zusammenfassung)

| Punkt | Neu | Geändert |
|------|-----|----------|
| 1 | — | `sql/invoice_header.sql`, `modules/invoice_fetcher.py`, `tests_slim/` |
| 2 | `slim/core_slim/access.py` | `slim/main_slim.py`, `app_settings.json.example`, `slim/README.md`, `slim/INSTALL.md`, `tests_slim/` |
| 3 | `slim/core_slim/clock.py` | `audit_jsonl.py`, `archive_fs.py`, `main_slim.py`, `run_now.py`, `updater.py`, `tests_slim/` |

## Nicht-Ziele
- Kein UI-Editor für `app_settings.json` (Konfig per Datei, Dienst-Neustart).
- Kein Auth-System; Allowlist ersetzt keine Authentifizierung.
- Keine Reverse-Proxy-/X-Forwarded-For-Auswertung.
- Keine Änderung an `logs/app.log` (bereits Lokalzeit).
