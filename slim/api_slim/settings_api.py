"""
slim/api_slim/settings_api.py
-----------------------------
Einstellungen in der Oberflaeche (nur Rolle 'verwalten', siehe auth_api).

- GET  /api/settings              alle Abschnitte laut settings_schema
- PUT  /api/settings/{abschnitt}  pruefen, sichern, atomar schreiben, auditieren
- GET  /api/settings/seller       Verkaeuferdaten: Suite8-Wert und Abweichung
- PUT  /api/settings/seller       Abweichungen speichern (hotel.json seller_overrides)
- POST /api/settings/db-test      gespeicherte Datenbankverbindung testen
- POST /api/system/restart        Dienst neu starten (NSSM)

Geheimnisse (DB-Passwort, Update-Token) werden nie zurueckgegeben und
verschluesselt gespeichert; ein leerer Wert bedeutet 'unveraendert'.
"""
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.config_loader import CONFIG_DIR
from core.crypto import encrypt, generate_key_file, load_key
from slim.core_slim import audit_jsonl
from slim.core_slim import settings_schema as schema

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

router = APIRouter(prefix="/api/settings", tags=["settings"])
system_router = APIRouter(prefix="/api/system", tags=["system"])

# Verkaeuferdaten, die die XML aus Suite8-WUSS bezieht (sql/invoice_header.sql)
SELLER_FIELDS = (
    ("supplierregistrationname", "UDEF_XRECHNUNG_FIRMIERUNG", "Rechtlicher Name (BT-27)"),
    ("suppliername", "Hotelid", "Handelsname (BT-28)"),
    ("supplierstreetname", "HotelAddress", "Strasse (BT-35)"),
    ("suppliercityname", "Hotelcity", "Ort (BT-37)"),
    ("supplierpostalzone", "Hotelzipcode", "PLZ (BT-38)"),
    ("suppliercompanyid", "HotelTaxNumber", "USt-IdNr. (BT-31)"),
    ("payeefinancialaccountid", "HotelbankIBAN", "IBAN (BT-84)"),
    ("payeefinancialaccountbic", "HotelbankBIC", "BIC (BT-86)"),
    ("payeefinancialaccountname", "UDEF_XRECHNUNG_FIRMIERUNG", "Kontoinhaber/Firmierung (BT-85)"),
    ("suppliercontacttelephone", "Hoteltel", "Telefon (BT-42)"),
    ("suppliercontactelectronicmail", "Hotelemail", "E-Mail (BT-43)"),
)


class Values(BaseModel):
    values: dict


def _path(name: str) -> Path:
    return Path(CONFIG_DIR) / name


def _load(name: str) -> dict:
    p = _path(name)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(500, f"{name} nicht lesbar: {e}")


_WRITE_LOCK = threading.RLock()   # Lesen-Aendern-Schreiben je Speichervorgang
_KEEP_BACKUPS = 20


def _write(name: str, data: dict) -> None:
    """Sicherung der alten Datei, dann atomar schreiben. Es bleiben die
    letzten _KEEP_BACKUPS Sicherungen je Datei."""
    p = _path(name)
    if p.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = p.with_name(f"{p.name}.{stamp}.sicherung")
        backup.write_bytes(p.read_bytes())
        old = sorted(p.parent.glob(f"{p.name}.*.sicherung"))
        for extra in old[:-_KEEP_BACKUPS]:
            try:
                extra.unlink()
            except OSError:
                pass
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _key() -> bytes:
    key_path = _path("connection.key")
    if not key_path.exists():
        generate_key_file(key_path)
    return load_key(key_path)


def _actor(request: Request) -> str:
    return getattr(request.state, "user", None) or "?"


def _field_view(s: schema.Setting, data: dict) -> dict:
    view = {"key": s.key, "label": s.label, "help": s.help, "type": s.type,
            "restart": s.restart, "choices": list(s.choices)}
    if s.type == "secret":
        view["gesetzt"] = bool(data.get(s.key))
    else:
        view["value"] = data.get(s.key, s.default)
    return view


@router.get("")
def get_settings():
    files = {}
    out = []
    for sec in schema.SECTIONS:
        fields = []
        for s in sec.settings:
            data = files.setdefault(s.file, _load(s.file))
            fields.append(_field_view(s, data))
        out.append({"id": sec.id, "label": sec.label, "fields": fields})
    return {"sections": out}


# --- Verkaeuferdaten (vor /{section}, damit 'seller' nicht als Abschnitt gilt) ---

def _suite8_seller_values() -> dict:
    """Aktuelle WUSS-Werte (nur SELECT), so gelesen wie in invoice_header.sql:
    Name ohne Gross-/Kleinschreibung, Hauswerte (xcms 0) bevorzugt, Firmierung
    faellt auf Hotelid zurueck, IBAN ohne Leerzeichen. Ohne DB: leeres Dict."""
    try:
        from core.db_connector import get_connection
        names = sorted({w.upper() for _, w, _ in SELLER_FIELDS})
        with get_connection() as conn:
            cur = conn.cursor()
            binds = ",".join(f":n{i}" for i in range(len(names)))
            cur.execute(f"select upper(wuss_name), wuss_value, wuss_xcms_id from wuss "
                        f"where upper(wuss_name) in ({binds}) order by nvl(wuss_xcms_id, 0)",
                        {f"n{i}": n for i, n in enumerate(names)})
            wuss: dict = {}
            for name, value, _ in cur.fetchall():
                wuss.setdefault(name, value)      # xcms 0 zuerst
        out = {k: wuss.get(w.upper()) for k, w, _ in SELLER_FIELDS}
        firm = wuss.get("UDEF_XRECHNUNG_FIRMIERUNG") or wuss.get("HOTELID")
        out["supplierregistrationname"] = firm
        out["payeefinancialaccountname"] = firm
        if out.get("payeefinancialaccountid"):
            out["payeefinancialaccountid"] = str(out["payeefinancialaccountid"]).replace(" ", "")
        return out
    except Exception as e:
        logger.warning("Suite8-Verkaeuferdaten nicht lesbar: %s", e)
        return {}


@router.get("/seller")
def get_seller():
    suite8 = _suite8_seller_values()
    overrides = _load("hotel.json").get("seller_overrides") or {}
    return [{"key": k, "label": label, "wuss": w, "suite8": suite8.get(k) or "",
             "abweichend": overrides.get(k, "")} for k, w, label in SELLER_FIELDS]


@router.put("/seller")
def put_seller(payload: Values, request: Request):
    allowed = {k for k, _, _ in SELLER_FIELDS}
    unknown = set(payload.values) - allowed
    if unknown:
        raise HTTPException(422, {k: "unbekanntes Feld" for k in unknown})
    with _WRITE_LOCK:
        hotel = _load("hotel.json")
        current = dict(hotel.get("seller_overrides") or {})
        for k, v in payload.values.items():
            v = "" if v is None else str(v).strip()
            if k == "payeefinancialaccountid":
                v = v.replace(" ", "")      # wie das Kopf-SQL
            if len(v) > 300:
                raise HTTPException(422, {k: "hoechstens 300 Zeichen"})
            if v:
                current[k] = v
            else:
                current.pop(k, None)
        hotel["seller_overrides"] = current
        _write("hotel.json", hotel)
    audit_jsonl.record_safe(DATA_DIR, "settings_changed",
                            details={"by": _actor(request), "file": "hotel.json",
                                     "keys": sorted(payload.values), "section": "seller"})
    return {"ok": True}


@router.post("/db-test")
def db_test():
    try:
        from core import db_connector
        db_connector.close_pool()          # alte Sitzungen sauber schliessen
        info = db_connector.test_connection()
        return {"ok": True, **info}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}


@router.put("/{section_id}")
def put_section(section_id: str, payload: Values, request: Request):
    try:
        sec = schema.section(section_id)
    except KeyError:
        raise HTTPException(404, "Unbekannter Abschnitt")
    by_key = {s.key: s for s in sec.settings}
    errors, changes = {}, {}
    for key, value in payload.values.items():
        s = by_key.get(key)
        if s is None:
            errors[key] = "unbekannte Einstellung in diesem Abschnitt"
            continue
        if s.type == "secret":
            if value in (None, ""):
                continue          # leer = unveraendert
            if not isinstance(value, str) or len(value) > 500:
                errors[key] = "ungueltig"
                continue
            changes[key] = ("secret", value)
            continue
        try:
            changes[key] = ("plain", schema.coerce(s, value))
        except schema.SettingError as e:
            errors[key] = str(e)
    # Neues Datenbankziel nur mit neu eingegebenem Passwort - sonst koennte ein
    # Verbindungstest das gespeicherte Passwort an einen fremden Server senden.
    if section_id == "datenbank" and "password" not in changes and not errors:
        stored = _load("connection.json")
        target = ("tns_alias", "username", "tns_admin", "oracle_client_lib_dir")
        if any(k in changes and changes[k][1] != stored.get(k, by_key[k].default or "")
               for k in target):
            errors["password"] = "bei geaendertem Datenbankziel bitte das Passwort neu eingeben"
    # Mindestens ein Erkennungsmuster muss bleiben, sonst erkennt der Poller
    # keine Rechnungsmail mehr (gleiche Regel wie die Pattern-Seite).
    if section_id == "versand" and not errors:
        hotel = _load("hotel.json")
        def _eff(k):
            if k in changes:
                return changes[k][1]
            return hotel.get(k, by_key[k].default)
        if not (_eff("suite8_recognize_subject_pattern") or _eff("suite8_recognize_filename_pattern")):
            errors["suite8_recognize_subject_pattern"] = "mindestens ein Erkennungsmuster (Betreff oder Dateiname) noetig"
    if errors:
        raise HTTPException(422, errors)
    if not changes:
        return {"ok": True, "restart": False}
    with _WRITE_LOCK:
        files: dict[str, dict] = {}
        for key, (kind, value) in changes.items():
            s = by_key[key]
            data = files.setdefault(s.file, _load(s.file))
            data[key] = encrypt(value, _key()) if kind == "secret" else value
        for name, data in files.items():
            _write(name, data)
    restart = any(by_key[k].restart for k in changes)
    for name in files:
        audit_jsonl.record_safe(DATA_DIR, "settings_changed",
                                details={"by": _actor(request), "file": name, "section": section_id,
                                         "keys": sorted(k for k in changes if by_key[k].file == name)})
    return {"ok": True, "restart": restart}


def _restart_service() -> None:
    from slim.core_slim import updater
    updater.restart_service_detached()


@system_router.post("/restart")
def restart(request: Request):
    audit_jsonl.record_safe(DATA_DIR, "service_restart", details={"by": _actor(request)})
    _restart_service()
    return {"ok": True}
