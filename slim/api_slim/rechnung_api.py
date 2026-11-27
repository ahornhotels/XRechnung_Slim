"""
slim/api_slim/rechnung_api.py
-----------------------------
Detailseite einer Rechnung - eine Seite fuer jeden Zustand:

  GET  /api/rechnung?nr=|wmai_id=[&fassung=aktuell]
        wartet        - Mail haengt in Suite8; Vorschau live aus Suite8
        gesendet      - Archivdatei, so wie sie an die Mail gehaengt wurde
        nachtraeglich - nachtraeglich erzeugt, nicht von Slim versendet
        archiviert    - Archivdatei ohne belegten Versand
        nie_erzeugt   - nur in Suite8; Vorschau live
  GET  /api/rechnung/kosit?nr=|wmai_id=   KoSIT-Pruefung der Vorschau (dauert Sekunden)
  POST /api/rechnung/erzeugen {nr}        nachtraeglich erzeugen und ablegen (nur 'verwalten')

Regeln:
- Ein GET schreibt nichts: keine Datei, kein Protokoll, keine Metadaten.
- Die Archivdatei einer gesendeten Rechnung wird nie ersetzt. "Heutiger Stand"
  (fassung=aktuell) baut nur im Speicher.
- Slim verschickt hier nichts. Nachtraeglich Erzeugtes ist als solches
  gekennzeichnet und nur zum Herunterladen da.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.config_loader import load_hotel_config
from core.db_connector import get_connection
from modules import invoice_fetcher, invoice_validator, kosit_validator, xml_builder
from modules.kosit_validator import KositValidationError
from modules.suite8_mailer import find_pending_wmai, get_wmai_error
from modules.suite8_pattern import AmbiguousMatchError, PatternMatchError, extract_zinv_number

from slim.api_slim import archive_api
from slim.api_slim.status import get_state
from slim.core_slim import archive_fs, audit_jsonl, overrides, xml_ansicht

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rechnung", tags=["rechnung"])

# So viele wartende Mails werden nach der Rechnung durchsucht.
_MAIL_SUCHE = 500
_VERLAUF_MAX = 200

# Ein nachtraegliches Erzeugen zur Zeit: zwei Klicks oder zwei Fenster liefen
# sonst beide an der Pruefung "liegt schon im Archiv?" vorbei.
_erzeugen_sperre = threading.Lock()


def _data_dir(state: dict) -> Path:
    data_dir = state.get("data_dir")
    if data_dir is None:
        raise HTTPException(500, "data_dir nicht initialisiert")
    return Path(data_dir)


def _muster() -> tuple[dict, str, str]:
    try:
        cfg = load_hotel_config() or {}
    except Exception:
        cfg = {}
    return (cfg, cfg.get("suite8_recognize_filename_pattern", "") or "",
            cfg.get("suite8_recognize_subject_pattern", "") or "")


def _treffer(row: dict, fn_pat: str, sub_pat: str):
    """(art, wert) der Rechnung, auf die eine wartende Mail zeigt - oder None."""
    try:
        return extract_zinv_number(filename=row["filename"], subject=row["subject"],
                                   filename_pattern=fn_pat, subject_pattern=sub_pat)
    except (PatternMatchError, AmbiguousMatchError):
        return None


def _wartende_mail(nr: Optional[str], wmai_id: Optional[int], zinv_id: Optional[int]):
    """Die wartende Mail zu einer Rechnungsnummer oder WMAI_ID.

    Returns (mail | None, nr). Wirft bei DB-Stoerung - der Aufrufer entscheidet,
    ob er ohne Datenbank weitermachen darf."""
    _, fn_pat, sub_pat = _muster()
    with get_connection() as conn:
        for row in find_pending_wmai(conn=conn, limit=_MAIL_SUCHE):
            t = _treffer(row, fn_pat, sub_pat)
            if t is None:
                continue
            art, wert = t
            if wmai_id is not None:
                if row["wmai_id"] != wmai_id:
                    continue
            elif not ((art == "zinv_number" and str(wert) == nr)
                      or (art == "zinv_id" and zinv_id is not None and int(wert) == zinv_id)):
                continue
            fehler = None
            try:
                fehler = get_wmai_error(row["wmai_id"], conn)
            except Exception:
                logger.exception("WMAI_ERROR nicht lesbar (wmai=%s)", row["wmai_id"])
            mail = {"wmai_id": row["wmai_id"], "subject": row["subject"], "filename": row["filename"],
                    "to": row["to"], "error": fehler, "zinv_id": int(wert) if art == "zinv_id" else None}
            return mail, (str(wert) if art == "zinv_number" else nr)
    return None, nr


def _archiv(data_dir: Path, nr: str) -> list[dict]:
    """Alle Archivdateien genau dieser Rechnungsnummer (kein Teilstring), die
    aktuelle Datei vor aelteren Versionen. Nutzt die Eintraege der Archivliste."""
    root = data_dir / "xml"
    if not root.exists():
        return []
    index = archive_fs.sent_index(data_dir)
    out = []
    for e in archive_api._all_entries(root, index):
        if str(e["rechnung"] or "") != nr:
            continue
        e = dict(e)
        e["echt"] = archive_api._echt(root / e["rel_path"])
        out.append(e)
    out.sort(key=lambda e: (not e["version"], e["_ts"]), reverse=True)
    for e in out:
        e.pop("_ts", None)
        e.pop("_meta_status", None)
    return out


def _verlauf(data_dir: Path, nr: str, wmai_ids: set) -> list[dict]:
    """Protokolleintraege zu dieser Rechnung (Nummer oder eine ihrer Mails), alt -> neu."""
    out = []
    for f in sorted(data_dir.glob("audit-*.jsonl")):
        try:
            zeilen = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in zeilen:
            if nr not in line and not any(str(w) in line for w in wmai_ids):
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if str(e.get("zinv_number") or "") == nr or (e.get("wmai_id") in wmai_ids):
                out.append(e)
    return out[-_VERLAUF_MAX:]


def _rechnung_laden(nr: str, zinv_id: Optional[int]) -> Optional[dict]:
    zid = zinv_id or invoice_fetcher.find_zinv_id_by_number(nr)
    return invoice_fetcher.fetch_invoice(zid) if zid else None


def _vorschau(inv: dict) -> dict:
    """Baut die XRechnung im Speicher. Scheitert der Bau an der Pruefung, wird
    wie bei der Fehlerablage ungeprueft gerendert, damit die Seite trotzdem
    zeigt, was Suite8 liefert."""
    pflicht = [i["message"] for i in invoice_validator.validate(inv)]
    bau_fehler = None
    xml = None
    try:
        xml = xml_builder.build_and_validate(inv)
    except Exception as e:
        bau_fehler = str(e)[:600]
        try:
            xml = xml_builder.render(inv)
        except Exception:
            logger.exception("Vorschau nicht renderbar")
    return {"xml": xml, "pflichtfelder": pflicht, "bau_fehler": None if pflicht and bau_fehler else bau_fehler,
            "ansicht": xml_ansicht.lies(xml) if xml else None}


def _nr_pruefen(nr: Optional[str], wmai_id: Optional[int]) -> Optional[str]:
    nr = (nr or "").strip() or None
    if nr is None and wmai_id is None:
        raise HTTPException(422, "Bitte eine Rechnungsnummer angeben.")
    return nr


@router.get("")
def detail(
    nr: Optional[str] = Query(default=None, max_length=64),
    wmai_id: Optional[int] = Query(default=None, ge=1),
    fassung: str = Query(default="", max_length=16),
    state: dict = Depends(get_state),
):
    data_dir = _data_dir(state)
    nr = _nr_pruefen(nr, wmai_id)

    db_fehler = None
    mail = None
    inv = None
    try:
        zinv_id = invoice_fetcher.find_zinv_id_by_number(nr) if nr else None
        mail, nr = _wartende_mail(nr, wmai_id, zinv_id)
        if mail and mail["zinv_id"]:
            zinv_id = mail["zinv_id"]
        if nr or zinv_id:
            inv = _rechnung_laden(nr or "", zinv_id)
            if inv is not None and not nr:
                nr = str((inv.get("header") or {}).get("id") or "") or None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Suite8-Zugriff fuer Rechnung %s fehlgeschlagen", nr)
        db_fehler = str(e)[:400]

    if not nr:
        if db_fehler:
            raise HTTPException(503, f"Suite8 nicht erreichbar: {db_fehler}")
        raise HTTPException(404, "Diese Mail wartet nicht (mehr) oder ist keine Rechnungsmail.")

    archiv = _archiv(data_dir, nr)
    if not archiv and mail is None and inv is None:
        if db_fehler:
            raise HTTPException(503, f"Suite8 nicht erreichbar: {db_fehler}")
        raise HTTPException(404, f"Rechnung {nr} ist weder im Archiv noch in Suite8 zu finden.")

    haupt = next((a for a in archiv if a["status"] == "gesendet" and not a["version"]), None) \
        or next((a for a in archiv if a["status"] == "gesendet"), None) \
        or (archiv[0] if archiv else None)
    if mail is not None:
        zustand = "wartet"
    elif haupt is None:
        zustand = "nie_erzeugt"
    elif haupt["status"] == "gesendet":
        zustand = "gesendet"
    elif haupt["nachtraeglich"]:
        zustand = "nachtraeglich"
    else:
        zustand = "archiviert"

    pruefung = None
    ansicht = None
    quelle = None
    live = mail is not None or haupt is None or fassung == "aktuell"
    if live and inv is not None:
        if mail is not None:
            mail["override"] = overrides.load(data_dir, mail["wmai_id"])
            inv = overrides.apply_to_invoice(data_dir, mail["wmai_id"], inv)
        v = _vorschau(inv)
        ansicht, quelle = v["ansicht"], "vorschau"
        pruefung = {"pflichtfelder": v["pflichtfelder"], "bau_fehler": v["bau_fehler"]}
        try:
            from modules import xrechnung_filter
            grund = xrechnung_filter.ausschlussgrund(inv, load_hotel_config() or {})
            pruefung["ausschluss"] = grund["text"] if grund else None
        except Exception:
            logger.exception("Filter-Einstellung nicht auswertbar")
    elif haupt is not None:
        try:
            ansicht = xml_ansicht.lies((data_dir / "xml" / haupt["rel_path"]).read_bytes())
            quelle = "archiv"
        except OSError as e:
            logger.exception("Archivdatei nicht lesbar: %s", haupt["rel_path"])
            db_fehler = db_fehler or f"Archivdatei nicht lesbar: {e}"
    if mail is not None:
        mail.setdefault("override", overrides.load(data_dir, mail["wmai_id"]))
        mail.pop("zinv_id", None)

    wmai_ids = {m for m in ([mail["wmai_id"]] if mail else [])}
    wmai_ids |= {a["wmai_id"] for a in archiv if a.get("wmai_id")}

    return {
        "nr": nr, "zustand": zustand, "quelle": quelle,
        "in_suite8": inv is not None,
        "wartend": mail, "archiv": archiv, "datei": haupt["rel_path"] if haupt else None,
        "ansicht": ansicht, "pruefung": pruefung,
        "verlauf": _verlauf(data_dir, nr, wmai_ids),
        "db_fehler": db_fehler,
    }


def _vorschau_fuer(nr: Optional[str], wmai_id: Optional[int], data_dir: Path) -> tuple[str, dict, Optional[dict]]:
    """(nr, rechnung mit Override, mail) fuer KoSIT und Erzeugen. Wirft HTTPException."""
    try:
        zinv_id = invoice_fetcher.find_zinv_id_by_number(nr) if nr else None
        mail, nr = _wartende_mail(nr, wmai_id, zinv_id)
        if mail and mail["zinv_id"]:
            zinv_id = mail["zinv_id"]
        inv = _rechnung_laden(nr or "", zinv_id) if (nr or zinv_id) else None
    except Exception as e:
        logger.exception("Suite8-Zugriff fuer Rechnung %s fehlgeschlagen", nr)
        raise HTTPException(503, f"Suite8 nicht erreichbar: {str(e)[:400]}")
    if inv is None:
        raise HTTPException(404, f"Rechnung {nr or ''} ist in Suite8 nicht zu finden.")
    nr = nr or str((inv.get("header") or {}).get("id") or "")
    if mail is not None:
        inv = overrides.apply_to_invoice(data_dir, mail["wmai_id"], inv)
    return nr, inv, mail


@router.get("/kosit")
def kosit(
    nr: Optional[str] = Query(default=None, max_length=64),
    wmai_id: Optional[int] = Query(default=None, ge=1),
    state: dict = Depends(get_state),
):
    """KoSIT-Pruefung des heutigen Stands. Schreibt nichts."""
    data_dir = _data_dir(state)
    nr = _nr_pruefen(nr, wmai_id)
    nr, inv, _ = _vorschau_fuer(nr, wmai_id, data_dir)
    try:
        xml = xml_builder.build_and_validate(inv)
    except Exception as e:
        return {"ok": False, "befunde": [f"XRechnung nicht baubar: {str(e)[:600]}"], "hinweis": None}
    try:
        kosit_validator.validate(xml)
    except FileNotFoundError as e:
        return {"ok": None, "befunde": [], "hinweis": f"KoSIT nicht verfügbar: {e}"}
    except KositValidationError as e:
        return {"ok": False, "befunde": [str(x)[:600] for x in (e.errors or [])][:50], "hinweis": None}
    return {"ok": True, "befunde": [], "hinweis": None}


class ErzeugenPayload(BaseModel):
    nr: str = Field(..., min_length=1, max_length=64)


@router.post("/erzeugen")
def erzeugen(payload: ErzeugenPayload, request: Request, state: dict = Depends(get_state)):
    """Eine Rechnung, die nie eine XRechnung hatte, nachtraeglich erzeugen und
    ins Archiv legen - gekennzeichnet, ohne Versand. Nur fehlerfrei."""
    data_dir = _data_dir(state)
    nr = payload.nr.strip()
    by = getattr(request.state, "user", None) or "?"
    if not _erzeugen_sperre.acquire(timeout=2):
        raise HTTPException(409, "Gerade wird eine andere Rechnung erzeugt. Bitte gleich noch einmal versuchen.")
    try:
        if _archiv(data_dir, nr):
            raise HTTPException(409, f"Rechnung {nr} liegt bereits im Archiv. Die Archivdatei wird nicht ersetzt.")
        nr, inv, mail = _vorschau_fuer(nr, None, data_dir)
        if mail is not None:
            raise HTTPException(
                409, f"Für Rechnung {nr} wartet eine Mail in Suite8. Die XRechnung entsteht, "
                     "sobald diese Mail verarbeitet wird.")
        issues = invoice_validator.validate(inv)
        if issues:
            raise HTTPException(422, "Pflichtfelder fehlen: " + "; ".join(i["message"] for i in issues[:10]))
        try:
            xml = xml_builder.build_and_validate(inv)
        except Exception as e:
            raise HTTPException(422, f"XRechnung nicht baubar: {str(e)[:600]}")
        try:
            kosit_validator.validate(xml)
        except FileNotFoundError as e:
            raise HTTPException(503, f"KoSIT nicht verfügbar, ohne Prüfung wird nichts abgelegt: {e}")
        except KositValidationError as e:
            raise HTTPException(422, "KoSIT-Prüfung nicht bestanden: " + "; ".join(str(x) for x in (e.errors or [])[:5])[:900])

        cfg, _, _ = _muster()
        filename = (cfg.get("suite8_attachment_name_template") or "{zinv_number}.xml").format(zinv_number=nr)
        arch = archive_fs.save_xml(data_dir, nr, xml, filename=filename,
                                   meta={"nachtraeglich": True, "erzeugt_von": by})
        audit_jsonl.record_safe(data_dir, "nachtraeglich_erzeugt", zinv_number=nr,
                                details={"by": by, "sha256": arch["sha256"], "xml_path": arch["xml_path"]})
        rel = Path(arch["xml_path"]).relative_to(data_dir / "xml").as_posix()
        return {"ok": True, "nr": nr, "rel_path": rel}
    finally:
        _erzeugen_sperre.release()
