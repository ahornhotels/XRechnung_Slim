"""
slim/api_slim/abrechnung_api.py
-------------------------------
Abrechnungsbericht (nur Kanal TBH), nur Rolle 'verwalten' (auth_api._ADMIN_PREFIXES).

  GET  /api/abrechnung          - Einstellung, Zahlen des letzten Monats (nur
                                  SELECT), bisher gesendete Berichte
  POST /api/abrechnung/senden   - Bericht jetzt in die Suite8-Mailwarteschlange
                                  legen {"monat": "JJJJ-MM"} (leer = letzter Monat)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core.config_loader import load_hotel_config
from slim.api_slim.status import get_state
from slim.core_slim.clock import now_local
from slim.jobs_slim import abrechnung

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/abrechnung", tags=["abrechnung"])


class SendenPayload(BaseModel):
    monat: Optional[str] = Field(default=None, max_length=7)


def _cfg() -> dict:
    try:
        return load_hotel_config() or {}
    except Exception:
        return {}


@router.get("")
def get_abrechnung(state: dict = Depends(get_state)):
    cfg, heute = _cfg(), now_local().date()
    data_dir = Path(state.get("data_dir") or ".")
    out = {"email": str(cfg.get("abrechnung_email") or ""), "tag": abrechnung._tag(cfg),
           "aktiv": bool(str(cfg.get("abrechnung_email") or "").strip()),
           "gesendet": abrechnung.stand_lesen(data_dir)["gesendet"], "vorschau": None, "fehler": None}
    try:
        out["vorschau"] = abrechnung.vorschau(cfg, heute)
    except Exception as e:
        logger.warning("Abrechnungsvorschau nicht moeglich: %s", e)
        out["fehler"] = "Suite8 ist nicht erreichbar, daher keine Zahlen."
    return out


@router.post("/senden")
def post_senden(payload: SendenPayload, request: Request, state: dict = Depends(get_state)):
    data_dir = Path(state.get("data_dir") or ".")
    by = getattr(request.state, "user", None) or "?"
    try:
        return {"ok": True, **abrechnung.senden(data_dir, _cfg(), now_local().date(),
                                                monat=payload.monat or None, von_hand=by)}
    except abrechnung.AbrechnungFehler as e:
        raise HTTPException(409, str(e))
    except Exception:
        logger.exception("Abrechnungsbericht von Hand fehlgeschlagen")
        raise HTTPException(503, "Bericht nicht gesendet: Suite8 ist nicht erreichbar oder lehnt die Mail ab.")
