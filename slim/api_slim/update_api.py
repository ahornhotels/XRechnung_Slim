"""
slim/api_slim/update_api.py
---------------------------
GitHub-Update-Endpoints:

  GET  /api/update/check  - prueft Release ohne Apply
  POST /api/update/apply  - Download + Apply + Service-Restart
  GET  /api/update/state  - letzter angewandter Stand

Keine Auth (Slim-Konvention: bind 127.0.0.1). Wer mit RDP-Zugriff am
Server sitzt, darf updaten.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from slim.core_slim import updater

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/update", tags=["update"])


@router.get("/check")
def update_check():
    """Liefert Status: current_version, latest_version, available, ..."""
    try:
        return updater.check_for_update()
    except updater.UpdateError as e:
        raise HTTPException(503, str(e))


@router.post("/apply")
def update_apply():
    """Führt das Update durch (synchron - Hotel-Mitarbeiter sieht das
    Ergebnis). Service-Restart läuft asynchron, ~4 s nach Response."""
    try:
        return updater.perform_full_update()
    except updater.UpdateError as e:
        raise HTTPException(503, str(e))


@router.get("/state")
def update_state():
    """Letzter persistierter Update-Stand."""
    return updater.load_state()
