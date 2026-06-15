"""
slim/api_slim/setup_api.py
--------------------------
Setup-Wizard-Endpoints für den Browser-Wizard (slim/frontend/setup.html).

Wizard-Schritte (8):
  1. Willkommen                (rein Frontend)
  2. Oracle-Verbindung         POST /api/setup/db/test, /save
  3. Hotel-Stammdaten          GET  /api/setup/wuss/standard
  4. UDEF-Keys                 GET  /api/setup/wuss/udef
                               POST /api/setup/wuss/udef
  5. BLOCKSEND-Trigger         GET  /api/setup/trigger-sql
  6. Pattern (subject/filename) POST /api/setup/pattern
  7. Hotel-Config              POST /api/setup/hotel
  8. Fertigstellen             POST /api/setup/finish
                               GET  /api/setup/status

Solange ``slim/config/.setup_done`` nicht existiert, ist der Wizard aktiv
und ``/`` redirected dort hin. Sobald gesetzt: 403 für alle Setup-
Endpoints, das normale UI laeuft.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from core.config_loader import CONFIG_DIR, load_json, save_json
from core.crypto import generate_key_file, load_key, encrypt
from core import db_connector
from modules.suite8_pattern import (
    validate_pattern as _validate_pattern_re, PatternMatchError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"])

SETUP_DONE_MARKER = CONFIG_DIR / ".setup_done"
KEY_PATH = CONFIG_DIR / "connection.key"


def _require_setup_mode():
    if SETUP_DONE_MARKER.exists():
        raise HTTPException(
            403, "Setup bereits abgeschlossen. Marker-Datei löschen um neu zu setupen."
        )


def _ensure_key() -> bytes:
    if not KEY_PATH.exists():
        generate_key_file(KEY_PATH)
    return load_key(KEY_PATH)


# ───────────────────────────── Status ─────────────────────────────

@router.get("/status")
async def setup_status():
    """Liefert was im Wizard schon gemacht wurde — fürs Frontend zum
    Wiederaufnehmen falls der Browser neu geladen wird."""
    conn_path = CONFIG_DIR / "connection.json"
    hotel_path = CONFIG_DIR / "hotel.json"

    conn = load_json(conn_path, default={}) or {}
    hotel = load_json(hotel_path, default={}) or {}

    return {
        "setup_done": SETUP_DONE_MARKER.exists(),
        "has_db_config": bool(conn.get("password")),
        "has_hotel": bool(hotel.get("hotel_code")),
        "has_pattern": bool(
            hotel.get("suite8_recognize_subject_pattern")
            or hotel.get("suite8_recognize_filename_pattern")
        ),
    }


# ───────────────────────────── DB ─────────────────────────────

class DbTestRequest(BaseModel):
    tns_alias: str = Field(..., min_length=1, max_length=200)
    username: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1)
    tns_admin: str = Field(default="", max_length=500)
    oracle_client_lib_dir: str = Field(default="", max_length=500)


@router.post("/db/test")
async def db_test(req: DbTestRequest):
    """Speichert die Connection probehalber + testet sie. Bei Erfolg bleibt
    sie liegen — der Wizard speichert nur DANN endgueltig wenn der Test
    durchgekommen ist."""
    _require_setup_mode()
    key = _ensure_key()
    cfg = {
        "tns_alias": req.tns_alias,
        "username": req.username,
        "password": encrypt(req.password, key),
        "tns_admin": req.tns_admin,
        "oracle_client_lib_dir": req.oracle_client_lib_dir,
    }
    save_json(CONFIG_DIR / "connection.json", cfg)
    db_connector._pool = None
    try:
        info = db_connector.test_connection()
        return {"ok": True, **info}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}


# ───────────────────────── Hotel-Stammdaten ─────────────────────────

REQUIRED_STANDARD = [
    ("HotelCode",      "Hotel-Code (SupplierID in XRechnung)"),
    ("Hotelid",        "Hotel-Name (SupplierName)"),
    ("HotelAddress",   "Straße + Hausnummer"),
    ("Hotelcity",      "Ort"),
    ("Hotelzipcode",   "PLZ"),
    ("Hotelcountry",   "Land (Langname, wird auf ISO2 aufgeloest)"),
    ("HotelTaxNumber", "USt-IdNr."),
    ("Hoteltel",       "Telefon"),
    ("Hotelemail",     "Hotel-E-Mail"),
    ("HotelbankIBAN",  "IBAN"),
    ("HotelbankBIC",   "BIC"),
    ("BaseCurrency",   "Basis-Waehrung (ZCUR_ID)"),
]


@router.get("/wuss/standard")
async def wuss_standard_check():
    """Liest die Hotel-Stammdaten aus WUSS und meldet was fehlt."""
    _require_setup_mode()
    try:
        with db_connector.get_connection() as conn:
            cur = conn.cursor()
            items = []
            for name, desc in REQUIRED_STANDARD:
                cur.execute(
                    "SELECT wuss_value FROM wuss "
                    "WHERE wuss_xcms_id = 0 AND wuss_name = :n",
                    {"n": name},
                )
                row = cur.fetchone()
                val = (row[0] or "").strip() if row else ""
                items.append({
                    "name": name, "desc": desc,
                    "value": val, "ok": bool(val),
                })
            return {
                "items": items,
                "missing_count": sum(1 for i in items if not i["ok"]),
            }
    except Exception as e:
        raise HTTPException(503, f"DB nicht erreichbar: {e}")


# ───────────────────────────── UDEF ─────────────────────────────

UDEF_DEFINITIONS = [
    {
        "name": "UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE",
        "default": "14",
        "label": "Tage bis Fälligkeit nach Rechnungsdatum",
        "required": True,
    },
    {
        "name": "UDEF_XRECHNUNG_RESPONSIBLE_NAME",
        "default": "Buchhaltung",
        "label": "Ansprechpartner Buchhaltung (BR-DE-5 Pflicht)",
        "required": True,
    },
    {
        "name": "UDEF_XRECHNUNG_FIRMIERUNG",
        "default": "",
        "label": "Offizielle Firmierung (leer = Hotel-Name wird genommen)",
        "required": False,
    },
]


@router.get("/wuss/udef")
async def wuss_udef_check():
    """Liefert pro UDEF-Key: Status, aktueller Wert (falls vorhanden), Default."""
    _require_setup_mode()
    try:
        with db_connector.get_connection() as conn:
            cur = conn.cursor()
            items = []
            for d in UDEF_DEFINITIONS:
                cur.execute(
                    "SELECT wuss_value FROM wuss "
                    "WHERE upper(wuss_name) = upper(:n)",
                    {"n": d["name"]},
                )
                row = cur.fetchone()
                present = row is not None
                value = (row[0] or "").strip() if row else ""
                items.append({
                    **d,
                    "present": present,
                    "current_value": value,
                })
            return {"items": items}
    except Exception as e:
        raise HTTPException(503, f"DB nicht erreichbar: {e}")


class UdefSavePayload(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)

    @field_validator("values")
    @classmethod
    def _no_overlong(cls, v):
        for k, vv in v.items():
            if len(vv) > 60:
                raise ValueError(f"{k}: WUSS_VALUE max 60 Zeichen")
        return v


@router.post("/wuss/udef")
async def wuss_udef_save(payload: UdefSavePayload):
    """Legt UDEF-Keys an (nur die, die NOCH NICHT existieren).

    Schreibt pro Key:
        INSERT INTO wuss (wuss_id, wuss_xcms_id, wuss_name, wuss_value)
        VALUES (seq_wuss.nextval, 0, :name, :value)

    Existierende Einträge werden NICHT angefasst.

    Returns:
      {"inserted": [...], "skipped_existing": [...], "blocked": [{name, error}]}
    """
    _require_setup_mode()
    allowed = {d["name"]: d for d in UDEF_DEFINITIONS}
    inserted: list[str] = []
    skipped: list[str] = []
    blocked: list[dict] = []

    try:
        with db_connector.get_connection() as conn:
            cur = conn.cursor()
            for name, value in payload.values.items():
                if name not in allowed:
                    continue  # ignorieren, nicht freigegeben
                value = (value or "").strip()
                d = allowed[name]
                if not value:
                    if d["required"]:
                        blocked.append({"name": name,
                                        "error": "Pflichtwert leer"})
                    continue

                # Existenz prüfen
                cur.execute(
                    "SELECT 1 FROM wuss WHERE upper(wuss_name) = upper(:n)",
                    {"n": name},
                )
                if cur.fetchone():
                    skipped.append(name)
                    continue

                try:
                    cur.execute(
                        "INSERT INTO wuss (wuss_id, wuss_xcms_id, wuss_name, wuss_value) "
                        "VALUES (seq_wuss.nextval, 0, :n, :v)",
                        {"n": name, "v": value[:60]},
                    )
                    conn.commit()
                    inserted.append(name)
                except Exception as e:
                    conn.rollback()
                    blocked.append({"name": name, "error": str(e)[:200]})

        return {
            "inserted": inserted,
            "skipped_existing": skipped,
            "blocked": blocked,
        }
    except Exception as e:
        raise HTTPException(503, f"DB nicht erreichbar: {e}")


# ─────────────────────────── Trigger-SQL ───────────────────────────

@router.get("/trigger-sql")
async def trigger_sql():
    """Rendert den BLOCKSEND-Trigger für den DBA, abhaengig vom
    konfigurierten Pattern (Filename oder Subject)."""
    _require_setup_mode()
    hotel = load_json(CONFIG_DIR / "hotel.json", default={}) or {}
    fn_pat = hotel.get("suite8_recognize_filename_pattern", "") or ""
    sub_pat = hotel.get("suite8_recognize_subject_pattern", "") or ""

    # Gemeinsamer Generator (inkl. Idempotenz-Guard + Oracle-Regex-Konvertierung),
    # damit Wizard und Post-Setup-Endpoint exakt identisches SQL liefern.
    from slim.api_slim.trigger_sql import build_block_trigger_sql
    sql = build_block_trigger_sql(fn_pat, sub_pat)
    return {"sql": sql, "has_filename_pattern": bool(fn_pat),
            "has_subject_pattern": bool(sub_pat)}


# ───────────────────────────── Pattern ─────────────────────────────

class PatternSavePayload(BaseModel):
    subject_pattern: str = Field(default="", max_length=500)
    filename_pattern: str = Field(default="", max_length=500)
    attachment_name_template: str = Field(default="{zinv_number}.xml",
                                           max_length=128)

    @field_validator("attachment_name_template")
    @classmethod
    def _name_must_contain_zinv(cls, v: str) -> str:
        if "{zinv_number}" not in v:
            raise ValueError("Template braucht den Platzhalter {zinv_number}")
        return v


@router.post("/pattern")
async def pattern_save(payload: PatternSavePayload):
    """Schreibt das Pattern in hotel.json. Validiert wie /api/config/pattern."""
    _require_setup_mode()
    for fld, value in (
        ("subject_pattern", payload.subject_pattern),
        ("filename_pattern", payload.filename_pattern),
    ):
        if value:
            try:
                _validate_pattern_re(value)
            except PatternMatchError as e:
                raise HTTPException(400, f"{fld}: {e}")
    if not payload.subject_pattern and not payload.filename_pattern:
        raise HTTPException(400, "Mindestens ein Pattern muss gesetzt sein.")

    hotel_path = CONFIG_DIR / "hotel.json"
    cfg = load_json(hotel_path, default={}) or {}
    cfg["suite8_recognize_subject_pattern"] = payload.subject_pattern
    cfg["suite8_recognize_filename_pattern"] = payload.filename_pattern
    cfg["suite8_attachment_name_template"] = payload.attachment_name_template
    cfg.setdefault("mail_strategy", "suite8")
    save_json(hotel_path, cfg)
    return {"ok": True}


# ───────────────────────────── Hotel ─────────────────────────────

class HotelSavePayload(BaseModel):
    hotel_code: str = Field(..., min_length=1, max_length=20)
    hotel_long_name: str = Field(..., min_length=1, max_length=200)
    absender_email: str = Field(default="", max_length=200)
    default_payment_terms_days: int = Field(default=14, ge=0, le=365)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    seller_contact_name: str = Field(default="", max_length=120)
    seller_contact_phone: str = Field(default="", max_length=60)
    seller_contact_email: str = Field(default="", max_length=200)


@router.post("/hotel")
async def hotel_save(payload: HotelSavePayload):
    """Schreibt hotel.json. Behält vorhandene Felder (Pattern usw.).

    mail_strategy wird HART auf 'suite8' gesetzt - sonst wuerde der
    Poller stillschweigend skipped, wenn die Datei z.B. von einer
    Big-App-Installation uebernommen wurde mit 'graph'.
    """
    _require_setup_mode()
    hotel_path = CONFIG_DIR / "hotel.json"
    cfg = load_json(hotel_path, default={}) or {}
    cfg.update(payload.model_dump())
    cfg.setdefault(
        "xrechnung_profile_id",
        "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0",
    )
    cfg["mail_strategy"] = "suite8"  # hart - kein setdefault
    cfg.setdefault("suite8_poll_interval_seconds", 30)
    save_json(hotel_path, cfg)
    return {"ok": True}


# ───────────────────────── Finish / Service ─────────────────────────

@router.post("/finish")
async def setup_finish():
    """Markiert Setup als abgeschlossen und (best-effort) installiert
    den NSSM-Service. Wenn install_slim.cmd nicht durchgeht (z.B. keine
    Admin-Rechte), wird das im Response gemeldet — der Operator startet
    es dann manuell.

    Pflicht-Check vorab: hotel.json, connection.json (mit password)
    müssen existieren UND ein Pattern muss gesetzt sein.
    """
    _require_setup_mode()
    hotel = load_json(CONFIG_DIR / "hotel.json", default={}) or {}
    conn = load_json(CONFIG_DIR / "connection.json", default={}) or {}

    if not conn.get("password"):
        raise HTTPException(400, "Oracle-Verbindung fehlt — Schritt 2 erst abschließen.")
    if not hotel.get("hotel_code"):
        raise HTTPException(400, "Hotel-Stammdaten fehlen — Schritt 7 erst abschließen.")
    if not (hotel.get("suite8_recognize_subject_pattern")
            or hotel.get("suite8_recognize_filename_pattern")):
        raise HTTPException(400, "Pattern fehlt — Schritt 6 erst abschließen.")

    # Service-Install: best-effort. Pfad zu install_slim.cmd ermitteln
    # über SUITE8_CONFIG_DIR (zeigt auf <repo>/slim/config → install ist ein Verzeichnis weiter oben).
    install_cmd = CONFIG_DIR.parent / "install" / "install_slim.cmd"
    service_status = {"attempted": False, "installed": False, "output": ""}
    if install_cmd.exists():
        service_status["attempted"] = True
        try:
            proc = subprocess.run(
                ["cmd.exe", "/c", str(install_cmd)],
                capture_output=True, text=True, timeout=60,
            )
            service_status["installed"] = (proc.returncode == 0)
            service_status["output"] = (proc.stdout + proc.stderr)[:2000]
            service_status["returncode"] = proc.returncode
        except Exception as e:
            service_status["output"] = f"{e}"

    SETUP_DONE_MARKER.write_text("done", encoding="utf-8")
    return {"ok": True, "service": service_status,
            "message": "Setup abgeschlossen. Wechsel zur Status-Seite."}
