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
import time
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


# Je Monatsordner (xml/JJJJ/MM) die fertig gelesenen Eintraege, gueltig bis
# sich der Ordner aendert (neue, umbenannte oder ersetzte Datei). So liest
# nicht jeder Seitenaufruf Zehntausende Metadateien neu.
_BUCKET_CACHE: dict = {}
_RACY_NS = 2_000_000_000


def _entry(p: Path, root: Path, meta: dict) -> dict:
    stat = p.stat()
    rel = p.relative_to(root)
    kosit = p.with_name(f"{p.stem}.kosit-report.xml")
    has_kosit = kosit.is_file()
    return {
        "rechnung": meta.get("rechnung"),
        "rechnungsdatum": meta.get("rechnungsdatum"),
        "art": meta.get("art"),
        "betrag": meta.get("betrag"),
        "waehrung": meta.get("waehrung"),
        "empfaenger": meta.get("empfaenger"),
        "angehaengt_am": meta.get("angehaengt_am"),
        "status": _status(meta),
        "_meta_status": meta.get("status"),
        "version": bool(archive_fs._VERSIONED_SUFFIX.search(p.name)),
        "kosit_report": kosit.relative_to(root).as_posix() if has_kosit else None,
        "name": p.name,
        "rel_path": rel.as_posix(),
        "bucket": rel.parent.as_posix(),
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
        "_ts": stat.st_mtime,
        "has_sha256": p.with_suffix(".sha256").exists(),
        "has_kosit_report": has_kosit,
    }


def _bucket_entries(bucket: Path, root: Path, index: dict) -> list:
    key = archive_fs.norm_path(bucket)
    try:
        sig = bucket.stat().st_mtime_ns
    except OSError:
        return []
    cached = _BUCKET_CACHE.get(key)
    if cached and cached[0] == sig:
        entries = cached[1]
        # Noch nicht als gesendet belegte Dateien gegen das Protokoll pruefen
        # (z. B. Statusdatei konnte nach dem Anhaengen nicht geschrieben werden)
        for i, e in enumerate(entries):
            if e["_meta_status"] == "archiviert" and index:
                p = root / e["rel_path"]
                if p.is_file():
                    meta = archive_fs.ensure_meta(p, index)
                    if meta.get("status") != "archiviert":
                        entries[i] = _entry(p, root, meta)
        return entries
    entries = []
    for p in sorted(bucket.glob("*.xml")):
        if not p.is_file() or p.name.endswith(".kosit-report.xml"):
            continue
        entries.append(_entry(p, root, archive_fs.ensure_meta(p, index)))
    try:
        sig = bucket.stat().st_mtime_ns      # ensure_meta kann Metadateien angelegt haben
    except OSError:
        return entries
    # Nur Ordner merken, die laenger nicht geaendert wurden: Windows-Zeitstempel
    # sind grob, eine Datei aus demselben Zeitschritt waere sonst unsichtbar.
    if time.time_ns() - sig > _RACY_NS:
        _BUCKET_CACHE[key] = (sig, entries)
    else:
        _BUCKET_CACHE.pop(key, None)
    return entries


def _all_entries(root: Path, index: dict):
    for bucket in sorted(d for d in root.glob("*/*") if d.is_dir()):
        yield from _bucket_entries(bucket, root, index)


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
    index = archive_fs.sent_index(Path(state["data_dir"]))
    items = []
    for e in _all_entries(root, index):
        nr = str(e["rechnung"] or "")
        if needle and needle not in e["name"].lower() and needle not in nr.lower():
            continue
        rd = e["rechnungsdatum"]
        if (von or bis) and not rd:
            continue
        if von and rd < von or bis and rd > bis:
            continue
        items.append(dict(e))

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
        i.pop("_meta_status", None)
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
