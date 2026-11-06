# Schritt 5: Oberfläche – Anmeldung und vollständige Konfiguration – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Slim bekommt eine Anmeldung mit den Rollen „ansehen“ und „verwalten“. Jede Einstellung aus `connection.json`, `hotel.json`, `app_settings.json` und `update.json` ist in der Oberfläche änderbar. Die Hoteldaten werden aus Suite8 gelesen und lassen sich überschreiben.

**Architecture:**
- **Bestehende Grundlage:** FastAPI und statische Seiten in `slim/frontend/` mit `fetch`. Daran wird nichts umgestellt.
- **Anmeldung:**
  - `slim/core_slim/auth.py` enthält Benutzerablage, Hashing, Sitzungen und die Sperre bei Fehlversuchen.
  - Eine Middleware in `slim/main_slim.py` hinter der IP-Freigabe prüft Sitzung und Rolle.
  - `slim/api_slim/auth_api.py` stellt Anmeldung, Abmeldung, Passwortänderung, Ersteinrichtung und Benutzerverwaltung bereit.
- **Einstellungen:**
  - `slim/core_slim/settings_schema.py` beschreibt jede Einstellung: Datei, Schlüssel, Typ, Erklärtext, ob geheim und ob ein Neustart nötig ist.
  - `slim/api_slim/settings_api.py` liest und schreibt die Dateien. Vor dem Schreiben legt es eine Sicherung an, schreibt atomar und protokolliert die Änderung im Audit.
- **Hoteldaten:** `hotel.json` → `seller_overrides` (Feld → Wert). `invoice_fetcher.fetch_invoice` wendet sie nach dem Kopf-SQL an. Die Seite zeigt dazu den aktuellen Suite8-Wert.
- **Seiten:** `login.html`, `settings.html`, `users.html`. `index.html` bekommt eine Kopfzeile mit Benutzer, Abmelden und Links.

**Spec:** `docs/superpowers/specs/2026-11-06-slim-umbau-design.md`, Abschnitt 10.

## Global Constraints

- **Passwort-Hash:** `hashlib.pbkdf2_hmac("sha256", pw, salt, 260_000)`, Salz 16 Byte, Ablage als `pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>`. Datei `slim/data/users.json`. Kein Klartext.
- **Sitzungen:**
  - Serverseitig im Speicher, Token per `secrets.token_urlsafe(32)`, Ablauf 8 h nach letzter Aktivität.
  - Cookie `slim_session` mit `HttpOnly`, `SameSite=Strict` und `Path=/`.
  - Ein Neustart beendet alle Sitzungen. Das ist gewollt.
- **Sperre:** 5 Fehlversuche je Benutzername innerhalb von 15 Minuten sperren 15 Minuten. Die Meldung ist immer neutral: „Anmeldung fehlgeschlagen“.
- **Rollen:**
  - `ansehen` darf alle `GET`-Anfragen, außer `/api/sql/*`, `/api/config/*`, `/api/settings*` und `/api/users*`.
  - `verwalten` darf alles.
  - `POST`, `PUT` und `DELETE` verlangen `verwalten`. Ausnahmen sind `/api/auth/logout` und `/api/auth/password` (eigenes Passwort).
- **Frei zugänglich:** `/healthz`, `/login`, `/api/auth/login`, `/api/auth/state` sowie `/setup` und `/api/setup/*` (dort greift der bestehende `_require_setup_mode`).
- **Ersteinrichtung:**
  - Gibt es keinen Benutzer, ist `POST /api/auth/bootstrap` (Name und Passwort) nur von localhost erlaubt. Danach antwortet es mit 403.
  - Ohne Benutzer leiten alle anderen Seiten auf `/login` um. Die Login-Seite zeigt bei localhost das Formular „Ersten Verwalter anlegen“, sonst einen Hinweis.
  - Der Poller läuft unabhängig davon weiter.
- **Letzter Verwalter:** lässt sich weder löschen noch herabstufen. Das ergibt eine 409.
- **Passwortregel:** mindestens 10 Zeichen. Bei `must_change` leitet jede Seite auf die Passwortänderung um.
- **Geheimnisse:** DB-Passwort und Update-Token werden nie zurückgegeben, nur `"gesetzt": true/false`. Ein leerer Wert beim Speichern bedeutet „unverändert“. Die Verschlüsselung ist Fernet wie bisher (`core/crypto.py`, Schlüssel wie im Setup-Wizard).
- **Speichern:**
  - Vorher `<datei>.<YYYYmmdd-HHMMSS>.sicherung` im selben Ordner anlegen.
  - Danach schreiben über eine temporäre Datei und `os.replace`.
  - Audit `settings_changed` mit Benutzer, Datei und Schlüsseln, ohne Werte.
- **Neustart:** `POST /api/system/restart` (nur `verwalten`) ruft `updater.restart_service_detached()` auf. Die Seite markiert Felder mit `restart: true`.
- **Erklärtexte:** Jede Schema-Einstellung hat einen nicht leeren `help`. Ein Test prüft das.
- **Nicht-Ziele:** keine Rechteverwaltung pro Seite über die zwei Rollen hinaus, kein Schreiben nach WUSS.
- Tests wie bisher, mit FastAPI `TestClient`. Nach jeder Aufgabe `/code-review high`.

## Review Focus

1. **Bestehende Installation nach dem Update ohne Benutzer:** Der Poller läuft, die Oberfläche von einem anderen Rechner zeigt den Hinweis, localhost kann den Verwalter anlegen (Task 2).
2. **Sitzung abgelaufen, während eine Seite offen ist:** `fetch` bekommt 401, die Seite leitet auf `/login` um (Task 2 und Task 6).
3. **Speichern mit leerem Passwortfeld:** Das gespeicherte DB-Passwort bleibt unverändert (Task 4).
4. **Gleichzeitige Fehlversuche verschiedener Benutzer:** Die Sperre gilt je Benutzer, ein anderer Benutzer bleibt anmeldbar (Task 1).
5. **Ungültige Eingabe** (Port als Text, ungültige IP): 422 mit Feldname, die Datei bleibt unverändert, es entsteht keine Sicherung (Task 4).

---

### Task 1: `slim/core_slim/auth.py`

**Produces:**
- `hash_password(pw) -> str`, `verify_password(pw, stored) -> bool`
- `UserStore(path)` mit `list()`, `get(name)`, `create(name, pw, role, must_change=True)`, `set_password(name, pw, must_change=False)`, `set_role(name, role)`, `delete(name)`, `count()`
- `SessionStore` mit `create(name) -> token`, `get(token) -> dict | None` (schiebt den Ablauf nach hinten), `drop(token)`, `drop_user(name)`
- `LoginGuard` mit `blocked(name) -> bool`, `fail(name)`, `ok(name)`
- Fehlerklasse `AuthError`

Tests in `tests_slim/test_auth_core.py`:
- Hash ist kein Klartext, falsches Passwort wird abgelehnt
- Letzter Verwalter ist geschützt
- Passwortlänge wird geprüft
- Sitzung läuft ab (Uhr injizierbar)
- Sperre nach 5 Fehlversuchen, je Benutzer
- Datei wird atomar geschrieben

### Task 2: Anmeldung im Server

**Files:** `slim/api_slim/auth_api.py`, `slim/main_slim.py` (Middleware und Routen `/login`), `slim/frontend/login.html`, `slim/api_slim/setup_api.py` (der Wizard legt den ersten Verwalter an: optionales Feld in `finish` oder eigener Schritt)

Endpunkte:
- `GET /api/auth/state` → `{users_exist, logged_in, user, role, must_change, local}`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `POST /api/auth/password`
- `POST /api/auth/bootstrap`

Tests in `tests_slim/test_auth_api.py`:
- ohne Sitzung 401 für die API und Umleitung für Seiten
- `ansehen` bekommt 403 bei POST und bei `/api/sql/*`
- `verwalten` darf alles
- Bootstrap nur lokal und nur ohne Benutzer
- Sperre nach 5 Fehlversuchen
- `must_change` erzwingt die Passwortänderung
- `/healthz` ist frei

### Task 3: Benutzerverwaltung

**Files:** `slim/api_slim/auth_api.py`
- `GET /api/users`
- `POST /api/users`
- `PUT /api/users/{name}` (Rolle und/oder neues Passwort, das neue Passwort setzt `must_change`)
- `DELETE /api/users/{name}`

Seite `slim/frontend/users.html`. Tests: Rechte, letzter Verwalter, beim Löschen werden die Sitzungen des Benutzers beendet.

### Task 4: Einstellungsschema und Einstellungs-API

**Files:** `slim/core_slim/settings_schema.py`, `slim/api_slim/settings_api.py`

Schema-Abschnitte, mit Typ und Prüfung:
- **Datenbank** (`connection.json`): `tns_alias`, `username`, `password` (geheim), `tns_admin`, `oracle_client_lib_dir`. Alle mit Neustart.
- **Hotel** (`hotel.json`): `hotel_code`, `currency`, `default_payment_terms_days`, Verkäuferkontakt `seller_contact_*`.
- **Versand** (`hotel.json`): `absender_email`, `suite8_recognize_subject_pattern`, `suite8_recognize_filename_pattern`, `suite8_poll_interval_seconds` (Neustart), `suite8_attachment_name_template`, `xml_only_all`, `xml_only_membership`.
- **Rechnungsinhalt** (`hotel.json`): `gastzeile`, `positionen_zusammenfassen`, `auslagen_artikel`.
- **Prüfung** (`app_settings.json`): `kosit_validation`, `xrechnung_version`.
- **Server** (`app_settings.json`): `host`, `port`, `allowed_ips`, `log_level`, `audit_retention_months`. Alle mit Neustart.
- **Update** (`update.json`): `enabled`, `owner`, `repo`, `pat_token` (geheim).

Endpunkte:
- `GET /api/settings` → Abschnitte mit Feldern `{key, label, help, type, value | gesetzt, restart}`
- `PUT /api/settings/{abschnitt}` → Prüfung, Sicherung, Schreiben, Audit
- `POST /api/settings/db-test` → Verbindungstest wie im Wizard
- `POST /api/system/restart`

Tests in `tests_slim/test_settings_api.py`:
- jedes Feld hat einen Erklärtext
- Geheimnisse werden nie zurückgegeben
- leeres Geheimnis bleibt unverändert
- Sicherung entsteht
- bei ungültiger Eingabe 422, keine Änderung, keine Sicherung
- unbekannte Schlüssel in der Datei bleiben erhalten
- Audit ohne Werte

### Task 5: Verkäuferdaten aus Suite8, überschreibbar

**Files:**
- `modules/invoice_fetcher.py`: `_apply_seller_overrides(header)` nach dem Kopf-SQL
- `slim/api_slim/settings_api.py`: Abschnitt „Verkäufer“ mit `GET /api/settings/seller` → je Feld der Suite8-Wert aus WUSS (per SELECT) und der abweichende Wert

Felder und WUSS-Quelle laut `sql/invoice_header.sql`:

| Feld | WUSS-Quelle |
|---|---|
| `suppliername` | Hotelid |
| `supplierstreetname` | HotelAddress |
| `suppliercityname` | Hotelcity |
| `supplierpostalzone` | Hotelzipcode |
| `suppliercompanyid` | HotelTaxNumber |
| `payeefinancialaccountid` | HotelbankIBAN |
| `payeefinancialaccountbic` | HotelbankBIC |
| `payeefinancialaccountname` | UDEF_XRECHNUNG_FIRMIERUNG |
| `suppliercontacttelephone` | Hoteltel |
| `suppliercontactelectronicmail` | Hotelemail |

- Ein leerer abweichender Wert bedeutet: Suite8 gilt.
- Die toten Felder `hotel_long_name` und `xrechnung_profile_id` werden in der Oberfläche nicht angeboten. In der Datei bleiben sie erhalten.
- Tests: Override greift, leer greift nicht, Audit.

### Task 6: Seiten

**Files:** `slim/frontend/settings.html`, `slim/frontend/users.html`, `slim/frontend/login.html`, `slim/frontend/index.html` (Kopfzeile, 401 → `/login`, Bedienelemente für `ansehen` ausblenden)

- Einstellungsseite: Abschnitte als Karten, Erklärtext je Feld, Hinweis „Neustart nötig“ und Knopf „Jetzt neu starten“, Verbindungstest, Felder „abweichend“ für die Verkäuferdaten.
- Test: Die Seiten werden ausgeliefert, und jede `fetch`-Antwort mit 401 führt zur Login-Umleitung (Quelltextprüfung).

### Task 7: Abschluss

- Gesamtsuite, Durchsicht auf echte Daten, STATUS.md, `README` und Release-Notes-Entwurf. Hinweis an die Häuser: Nach dem Update am Server den ersten Verwalter anlegen.
- Prüfen, ob `updater.restart_service_detached` nach jedem Update läuft. Laut OPERA führen alter Code und neue Templates sonst zu HTTP 500.
