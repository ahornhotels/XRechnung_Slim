"""
slim/api_slim/retry.py
----------------------
Retry-/Override-Endpoints:

  POST /api/wmai/{wmai_id}/retry        - WMAI_ERROR=NULL für eine WMAI
  POST /api/wmai/retry-all              - WMAI_ERROR=NULL für ALLE pending
                                          mit aktuell gesetztem Error

  GET  /api/wmai/{wmai_id}/override     - aktuelle Override-Werte lesen
  POST /api/wmai/{wmai_id}/override     - Override-Werte schreiben
  DELETE /api/wmai/{wmai_id}/override   - Override löschen
  GET  /api/overrides                   - Liste aller pending Overrides
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam
from pydantic import BaseModel, Field

from core.db_connector import get_connection
from modules.suite8_mailer import set_wmai_error, find_pending_wmai, get_wmai_error

from slim.core_slim import audit_jsonl, overrides
from slim.api_slim.status import get_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["retry"])


# ─────────────────────────── Single-Retry ───────────────────────────

@router.post("/wmai/{wmai_id}/retry")
def retry_wmai(
    wmai_id: int = PathParam(..., ge=1),
    state: dict = Depends(get_state),
):
    """Cleart WMAI_ERROR für eine WMAI und auditiert den Re-Trigger."""
    try:
        with get_connection() as conn:
            set_wmai_error(wmai_id, None, conn)
    except Exception as e:
        logger.exception("Retry für WMAI %s fehlgeschlagen", wmai_id)
        raise HTTPException(status_code=503, detail=f"DB nicht erreichbar: {e}")

    data_dir = state.get("data_dir")
    if data_dir is not None:
        audit_jsonl.record_safe(
            Path(data_dir), "retry_triggered",
            wmai_id=wmai_id, zinv_number=None,
            details={"source": "api"},
        )
    return {"ok": True, "wmai_id": wmai_id}


# ─────────────────────────── Bulk-Retry ───────────────────────────

@router.post("/wmai/retry-all")
def retry_all(state: dict = Depends(get_state)):
    """Cleart WMAI_ERROR für ALLE aktuell pending WMAIs mit gesetztem Error.

    Sammelt vorher die Ids ein, damit der Audit-Eintrag pro Aktion ein
    klares Vorher-Bild liefert. Verwendet eine einzige Connection — bei
    Verbindungsabbruch wird abgebrochen und der Erfolg im Response gemeldet.
    """
    cleared: list[int] = []
    failed: list[dict] = []

    try:
        with get_connection() as conn:
            pending = find_pending_wmai(conn=conn, limit=500)
            # Nur WMAIs anfassen, die TATSAECHLICH einen Fehler haben.
            with_error: list[int] = []
            for row in pending:
                try:
                    err = get_wmai_error(row["wmai_id"], conn) or ""
                except Exception:
                    err = ""
                if err.strip():
                    with_error.append(row["wmai_id"])

            for wmai_id in with_error:
                try:
                    set_wmai_error(wmai_id, None, conn)
                    cleared.append(wmai_id)
                except Exception as e:
                    failed.append({"wmai_id": wmai_id, "error": str(e)[:200]})
    except Exception as e:
        logger.exception("Bulk-Retry fehlgeschlagen")
        raise HTTPException(status_code=503, detail=f"DB nicht erreichbar: {e}")

    data_dir = state.get("data_dir")
    if data_dir is not None:
        audit_jsonl.record_safe(
            Path(data_dir), "retry_triggered",
            wmai_id=None, zinv_number=None,
            details={"source": "api", "bulk": True,
                     "cleared_count": len(cleared),
                     "failed_count": len(failed),
                     "cleared_ids": cleared[:50]},  # Cap für Audit-Lesbarkeit
        )

    return {
        "ok": True,
        "cleared_count": len(cleared),
        "failed_count": len(failed),
        "cleared_ids": cleared,
        "failures": failed,
    }


# ─────────────────────────── Overrides ───────────────────────────

class OverridePayload(BaseModel):
    """Frei-formatige Override-Werte. Server-Side filtert auf erlaubte
    Keys (siehe slim.core_slim.overrides.ALLOWED_KEYS)."""
    values: dict[str, str] = Field(default_factory=dict)


@router.get("/wmai/{wmai_id}/override")
def get_override(
    wmai_id: int = PathParam(..., ge=1),
    state: dict = Depends(get_state),
):
    data_dir = state.get("data_dir")
    if data_dir is None:
        raise HTTPException(500, "data_dir nicht initialisiert")
    return {
        "wmai_id": wmai_id,
        "values": overrides.load(Path(data_dir), wmai_id),
        "allowed_keys": sorted(overrides.ALLOWED_KEYS),
    }


@router.post("/wmai/{wmai_id}/override")
def post_override(
    payload: OverridePayload,
    wmai_id: int = PathParam(..., ge=1),
    state: dict = Depends(get_state),
):
    data_dir = state.get("data_dir")
    if data_dir is None:
        raise HTTPException(500, "data_dir nicht initialisiert")

    # Prüfen, dass keine unbekannten Keys übergeben werden (defensiv —
    # save() filtert ohnehin, aber dem User soll im UI klar gemeldet
    # werden was wirklich gespeichert wurde).
    unknown = [k for k in payload.values if k not in overrides.ALLOWED_KEYS]
    if unknown:
        raise HTTPException(
            400,
            f"Folgende Felder sind nicht überschreibbar: {', '.join(unknown)}. "
            f"Erlaubt sind: {', '.join(sorted(overrides.ALLOWED_KEYS))}",
        )

    saved = overrides.save(Path(data_dir), wmai_id, payload.values)
    audit_jsonl.record_safe(
        Path(data_dir), "override_saved",
        wmai_id=wmai_id,
        details={"fields": sorted(saved.keys())},
    )
    # Implizit auch WMAI_ERROR clearen, damit der nächste Poll-Lauf die
    # WMAI mit dem Override verarbeitet (sonst müsste der Operator zwei
    # Klicks machen: Override speichern + Retry).
    try:
        with get_connection() as conn:
            set_wmai_error(wmai_id, None, conn)
    except Exception:
        logger.exception("WMAI_ERROR-Clear nach Override-Save fehlgeschlagen "
                         "(wmai=%s)", wmai_id)
    return {"ok": True, "wmai_id": wmai_id, "saved": saved}


@router.delete("/wmai/{wmai_id}/override")
def delete_override(
    wmai_id: int = PathParam(..., ge=1),
    state: dict = Depends(get_state),
):
    data_dir = state.get("data_dir")
    if data_dir is None:
        raise HTTPException(500, "data_dir nicht initialisiert")
    deleted = overrides.delete(Path(data_dir), wmai_id)
    if deleted:
        audit_jsonl.record_safe(
            Path(data_dir), "override_deleted", wmai_id=wmai_id,
        )
    return {"ok": True, "wmai_id": wmai_id, "deleted": deleted}


@router.get("/overrides")
def list_overrides(state: dict = Depends(get_state)):
    """Listet alle gespeicherten Overrides — für das UI sichtbar."""
    data_dir = state.get("data_dir")
    if data_dir is None:
        raise HTTPException(500, "data_dir nicht initialisiert")
    return {"items": overrides.list_all(Path(data_dir))}
