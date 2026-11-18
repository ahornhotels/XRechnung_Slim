"""
slim/api_slim/archive_api.py
----------------------------
Read-only Zugriff auf das Filesystem-XML-Archiv (slim/data/xml/...):

  GET /api/archive            — Listing (neueste zuerst, Filter, Limit)
  GET /api/archive/file       — Download einer Archivdatei (.xml/.sha256)
  GET /api/archive/verify     — SHA256 gegen die Seitendatei pruefen
  GET /api/archive/ansicht    — lesbare Rechnung + Original-XML

Liste mit Metadaten je Datei (<stem>.meta.json, Bestandsdateien werden einmalig
nachgetragen): Rechnungsdatum, Art, Betrag, Empfaenger, Status, Echtheit.

Kein Auth — bind nur auf 127.0.0.1 (wie alle Slim-Endpoints).
Kein Index, keine DB: das Filesystem ist die Quelle der Wahrheit.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from slim.api_slim.status import get_state
from slim.core_slim import archive_fs, xml_ansicht

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


def _datum(value: Optional[str], name: str) -> Optional[str]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise HTTPException(422, f"{name}: Datum bitte als JJJJ-MM-TT")


def _echt(p: Path) -> Optional[bool]:
    sidecar = p.with_suffix(".sha256")
    if not sidecar.is_file():
        return None
    try:
        expected = sidecar.read_text(encoding="utf-8").split()[0].lower()
    except (OSError, IndexError):
        return False
    return hashlib.sha256(p.read_bytes()).hexdigest() == expected


def _status(meta: dict) -> str:
    if meta.get("status") == "gesendet":
        return "gesendet"
    # Bestandsdatei ohne attach_ok im Protokoll: ob sie gesendet wurde, ist
    # nicht mehr belegbar (Protokoll evtl. schon geloescht)
    return "unbekannt" if meta.get("nachgetragen") else "nicht angehängt"


@router.get("")
def list_archive(
    q: Optional[str] = Query(default=None, max_length=200),
    von: Optional[str] = Query(default=None, max_length=10),
    bis: Optional[str] = Query(default=None, max_length=10),
    limit: int = Query(default=100, ge=1, le=1000),
    state: dict = Depends(get_state),
):
    """Listet archivierte XMLs (ohne KoSIT-Reports), neuestes Rechnungsdatum zuerst.

    q filtert Rechnungsnummer oder Dateiname, von/bis (inklusiv) das Rechnungsdatum."""
    von, bis = _datum(von, "von"), _datum(bis, "bis")
    root = _xml_root(state)
    if not root.exists():
        return {"items": [], "count": 0}

    needle = (q or "").lower()
    index = None
    items = []
    for p in root.rglob("*.xml"):
        if not p.is_file() or p.name.endswith(".kosit-report.xml"):
            continue
        if not archive_fs.meta_path(p).exists() and index is None:
            index = archive_fs.sent_index(Path(state["data_dir"]))
        meta = archive_fs.ensure_meta(p, index or {})
        nr = str(meta.get("rechnung") or "")
        if needle and needle not in p.name.lower() and needle not in nr.lower():
            continue
        rd = meta.get("rechnungsdatum")
        if (von or bis) and not rd:
            continue
        if von and rd < von or bis and rd > bis:
            continue
        stat = p.stat()
        rel = p.relative_to(root)
        kosit = p.with_name(f"{p.stem}.kosit-report.xml")
        items.append({
            "rechnung": meta.get("rechnung"),
            "rechnungsdatum": rd,
            "art": meta.get("art"),
            "betrag": meta.get("betrag"),
            "waehrung": meta.get("waehrung"),
            "empfaenger": meta.get("empfaenger"),
            "angehaengt_am": meta.get("angehaengt_am"),
            "status": _status(meta),
            "version": bool(archive_fs._VERSIONED_SUFFIX.search(p.name)),
            "kosit_report": kosit.relative_to(root).as_posix() if kosit.is_file() else None,
            "name": p.name,
            "rel_path": rel.as_posix(),
            "bucket": rel.parent.as_posix(),
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(
                stat.st_mtime
            ).astimezone().isoformat(),
            "_ts": stat.st_mtime,
            "has_sha256": p.with_suffix(".sha256").exists(),
            "has_kosit_report": p.with_name(
                f"{p.stem}.kosit-report.xml"
            ).exists(),
        })

    # Je Rechnungsnummer die zuletzt gesendete Version markieren
    latest: dict = {}
    for i in items:
        if i["status"] == "gesendet" and i["rechnung"]:
            cur = latest.get(i["rechnung"])
            if cur is None or (i["angehaengt_am"] or "") > (cur["angehaengt_am"] or ""):
                latest[i["rechnung"]] = i
    for i in items:
        i["zuletzt_gesendet"] = latest.get(i["rechnung"]) is i

    items = _sort_items(items)[:limit]
    for i in items:
        i.pop("_ts", None)
        i["echt"] = _echt(root / i["rel_path"])
    return {"items": items, "count": len(items)}


def _sort_items(items: list) -> list:
    """Neuestes Rechnungsdatum zuerst, dann nach Datei-Zeitpunkt (Epoch ``_ts``) —
    NICHT nach dem ``mtime``-Anzeigestring: der traegt lokale Offsets
    (+01:00/+02:00), deren lexikografische Ordnung ueber einen DST-Wechsel nicht
    chronologisch ist."""
    items.sort(key=lambda i: (i.get("rechnungsdatum") or "", i["_ts"], i["name"]), reverse=True)
    return items


@router.get("/ansicht")
def ansicht(
    path: str = Query(..., max_length=500),
    state: dict = Depends(get_state),
):
    """Lesbare Rechnung aus der archivierten XML, dazu der Originaltext."""
    target = _resolve_safe(_xml_root(state), path)
    raw = target.read_bytes()
    data = xml_ansicht.lies(raw)
    if data is None:
        raise HTTPException(422, "Keine lesbare XRechnung")
    data["xml"] = raw.decode("utf-8", errors="replace")
    return data


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
