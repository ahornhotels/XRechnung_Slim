"""
slim/api_slim/status.py
-----------------------
Read-only API: Status, Pending-Liste, Audit-Tail.
Kein Auth - bind nur auf 127.0.0.1.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.config_loader import load_hotel_config
from core.db_connector import get_connection
from modules.suite8_mailer import find_pending_wmai, get_wmai_error

from slim.core_slim import audit_jsonl

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["status"])


# Wird vom main_slim.py per Dependency-Override gefüllt, damit
# Test-Code data_dir / state-dict einfach ersetzen kann.
_STATE: dict = {"data_dir": None, "last_run": None,
                "last_run_summary": None, "interval_seconds": 30}


def get_state() -> dict:
    return _STATE


@router.get("/status")
def status(state: dict = Depends(get_state)):
    mail_strategy = None
    pattern_set = False
    try:
        cfg = load_hotel_config()
        hotel = cfg.get("hotel_code") or cfg.get("hotel_long_name") or "?"
        mail_strategy = cfg.get("mail_strategy")
        pattern_set = bool(
            cfg.get("suite8_recognize_subject_pattern")
            or cfg.get("suite8_recognize_filename_pattern")
        )
    except FileNotFoundError:
        hotel = None

    # Warnsignal sammeln — UI zeigt das oben prominent an
    warnings = []
    last_summary = state.get("last_run_summary") or {}
    if mail_strategy and mail_strategy not in ("suite8", "auto"):
        warnings.append(
            f"mail_strategy={mail_strategy!r} - Poller wird SKIPPED. "
            f"In hotel.json auf 'suite8' setzen, dann Service neu starten."
        )
    if last_summary.get("skipped_strategy"):
        warnings.append(
            "Letzter Lauf wurde wegen mail_strategy SKIPPED - keine Verarbeitung."
        )
    if not pattern_set:
        warnings.append("Kein Pattern konfiguriert - keine WMAIs werden gematched.")

    return {
        "service": "Suite8XRechnungSlim",
        "hotel": hotel,
        "mail_strategy": mail_strategy,
        "pattern_configured": pattern_set,
        "warnings": warnings,
        "interval_seconds": state.get("interval_seconds"),
        "last_run": state.get("last_run"),
        "last_run_summary": last_summary or None,
        "now": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/pending")
def pending():
    """Liefert die aktuellen WMAI-Einträge mit BLOCKSEND=1 + WMAI_ERROR."""
    try:
        with get_connection() as conn:
            rows = find_pending_wmai(conn=conn, limit=50)
            enriched = []
            for r in rows:
                err = None
                try:
                    err = get_wmai_error(r["wmai_id"], conn)
                except Exception:
                    pass
                enriched.append({
                    "wmai_id": r["wmai_id"],
                    "filename": r["filename"],
                    "subject": r["subject"],
                    "to": r["to"],
                    "error": err,
                })
            return {"items": enriched, "count": len(enriched)}
    except Exception as e:
        logger.exception("Pending-Liste fehlgeschlagen")
        raise HTTPException(status_code=503, detail=f"DB nicht erreichbar: {e}")


@router.get("/audit/tail")
def audit_tail(
    n: int = Query(default=100, ge=1, le=2000),
    state: dict = Depends(get_state),
):
    data_dir = state.get("data_dir")
    if data_dir is None:
        raise HTTPException(500, "data_dir nicht initialisiert")
    entries = audit_jsonl.tail(Path(data_dir), n=n)
    return {"items": entries, "count": len(entries)}
