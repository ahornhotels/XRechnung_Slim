"""
slim/api_slim/archive_api.py
----------------------------
Read-only Zugriff auf das Filesystem-XML-Archiv (slim/data/xml/...):

  GET /api/archive            — Listing (neueste zuerst, Filter, Limit)
  GET /api/archive/file       — Download einer Archivdatei (.xml/.sha256)
  GET /api/archive/verify     — SHA256 gegen die Seitendatei pruefen

Kein Auth — bind nur auf 127.0.0.1 (wie alle Slim-Endpoints).
Kein Index, keine DB: das Filesystem ist die Quelle der Wahrheit.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from slim.api_slim.status import get_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/archive", tags=["archive"])

_ALLOWED_SUFFIXES = (".xml", ".sha256")


def _xml_root(state: dict) -> Path:
    data_dir = state.get("data_dir")
    if data_dir is None:
        raise HTTPException(500, "data_dir nicht initialisiert")
    return Path(data_dir) / "xml"


def _resolve_safe(root: Path, rel_path: str) -> Path:
    """Loest einen relativen Archiv-Pfad auf und blockt Traversal.

    Alles, was nach resolve() nicht unterhalb des xml-Roots liegt
    (../, absolute Pfade, Symlink-Tricks), liefert 404 — bewusst kein
    403, um nicht zu verraten, was ausserhalb existiert.
    """
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(404, "Datei nicht gefunden")
    if candidate.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise HTTPException(404, "Datei nicht gefunden")
    if not candidate.is_file():
        raise HTTPException(404, "Datei nicht gefunden")
    return candidate


@router.get("")
def list_archive(
    q: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=1000),
    state: dict = Depends(get_state),
):
    """Listet archivierte XMLs (ohne KoSIT-Reports), neueste zuerst."""
    root = _xml_root(state)
    if not root.exists():
        return {"items": [], "count": 0}

    needle = (q or "").lower()
    items = []
    for p in root.rglob("*.xml"):
        if not p.is_file() or p.name.endswith(".kosit-report.xml"):
            continue
        if needle and needle not in p.name.lower():
            continue
        stat = p.stat()
        rel = p.relative_to(root)
        items.append({
            "name": p.name,
            "rel_path": rel.as_posix(),
            "bucket": rel.parent.as_posix(),
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
            "has_sha256": p.with_suffix(".sha256").exists(),
            "has_kosit_report": p.with_name(
                f"{p.stem}.kosit-report.xml"
            ).exists(),
        })

    items.sort(key=lambda i: (i["mtime"], i["name"]), reverse=True)
    items = items[:limit]
    return {"items": items, "count": len(items)}


@router.get("/file")
def download_file(
    path: str = Query(..., max_length=500),
    state: dict = Depends(get_state),
):
    """Liefert eine Archivdatei als Download (Content-Disposition: attachment)."""
    target = _resolve_safe(_xml_root(state), path)
    return FileResponse(
        target,
        filename=target.name,
        media_type="application/xml" if target.suffix == ".xml" else "text/plain",
        content_disposition_type="attachment",
    )


@router.get("/verify")
def verify_file(
    path: str = Query(..., max_length=500),
    state: dict = Depends(get_state),
):
    """Berechnet den SHA256 einer Archiv-XML neu und vergleicht mit der
    .sha256-Seitendatei (Tampering-Pruefung).

    Returns:
        {"ok": bool, "expected": str | None, "actual": str}
    """
    target = _resolve_safe(_xml_root(state), path)
    actual = hashlib.sha256(target.read_bytes()).hexdigest()

    expected: Optional[str] = None
    sidecar = target.with_suffix(".sha256")
    if sidecar.is_file():
        # Format wie `sha256sum`: "<hex>  <filename>"
        first_token = sidecar.read_text(encoding="utf-8").strip().split()
        if first_token:
            expected = first_token[0].lower()

    return {
        "ok": expected is not None and expected == actual,
        "expected": expected,
        "actual": actual,
    }
