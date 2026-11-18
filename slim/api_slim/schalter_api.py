"""
slim/api_slim/schalter_api.py
-----------------------------
XRechnung ein/aus: schaltet den Suite8-Trigger WMAI_XRECHNUNG_BLOCK.

  GET  /api/schalter          - echter Zustand aus der Datenbank (Rolle ansehen)
  POST /api/schalter {"ein"}  - Trigger ENABLE/DISABLE (nur verwalten, ueber die
                                Regel "nicht-GET = verwalten" in auth_api)

Aus: neue Rechnungsmails gehen ohne XRechnung (nur PDF) raus; bereits
gesperrte Mails bleiben gesperrt, weil der Poller bei inaktivem Trigger nichts
verarbeitet. Ein: Trigger aktiv, wartende Mails werden verarbeitet.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StrictBool

from core.db_connector import get_connection
from slim.api_slim.status import get_state
from slim.core_slim import audit_jsonl, trigger_state, verarbeitung

router = APIRouter(prefix="/api/schalter", tags=["schalter"])


class SchalterPayload(BaseModel):
    ein: StrictBool


def _read() -> dict:
    try:
        with get_connection() as conn:
            return trigger_state.read_state(conn)
    except Exception as e:
        return {"state": "nicht_pruefbar", "owner": None, "user": None,
                "grant_sql": None, "error": str(e)[:500]}


@router.get("")
def get_schalter():
    return _read()


@router.post("")
def post_schalter(payload: SchalterPayload, request: Request, state: dict = Depends(get_state)):
    data_dir = state.get("data_dir")
    by = getattr(request.state, "user", None) or "?"
    try:
        with get_connection() as conn:
            vorher = trigger_state.read_state(conn)["state"]
            nachher = trigger_state.set_enabled(conn, payload.ein)
        if payload.ein:
            # Altwert der entfernten Einstellung "Verarbeitung = aus" darf "EIN"
            # nicht still aushebeln.
            verarbeitung.aus_aufheben()
    except trigger_state.TriggerSchaltFehler as e:
        if data_dir is not None:
            audit_jsonl.record_safe(Path(data_dir), "schalter_geaendert",
                                    details={"by": by, "ein": payload.ein, "error": str(e)})
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(503, f"Datenbank nicht erreichbar: {e}")
    if data_dir is not None:
        audit_jsonl.record_safe(Path(data_dir), "schalter_geaendert",
                                details={"by": by, "vorher": vorher, "nachher": nachher["state"]})
    return nachher
