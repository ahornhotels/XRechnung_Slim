"""
slim/core_slim/overrides.py
---------------------------
Pro-WMAI-Overrides für Header-Felder, die der Validator als fehlend
markiert hat (z.B. fehlende Kunden-E-Mail, leere BuyerReference).

Layout im Filesystem:
  <data_dir>/overrides/<wmai_id>.json

Inhalt: flaches Dict mit Header-Keys (lowercase, so wie sie
``invoice_fetcher.fetch_invoice`` zurueckgibt). Beim Poller-Lauf werden
die Werte nach dem Fetch in ``invoice['header']`` gemerget — Schlüssel
mit None / leeren Strings werden ignoriert, damit der Operator gezielt
einzelne Felder ergänzen kann.

Nach erfolgreichem ``attach_ok`` wird die Override-Datei
**automatisch gelöscht** (verhindert, dass der Override bei einer
Folge-WMAI mit gleicher ID dranbleibt — WMAI-IDs sind eindeutig pro
DB, aber Re-Inserts sind in der Praxis selten).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Whitelist editierbarer Header-Keys — verhindert, dass jemand z.B. die
# Rechnungs-ID oder das Datum überschreibt und damit die Rechnung
# unterschiebt. Diese Liste deckt die Pflichtfelder aus
# invoice_validator.REQUIRED_HEADER_FIELDS ab.
ALLOWED_KEYS = frozenset({
    "suppliername",
    "supplierstreetname",
    "suppliercityname",
    "supplierpostalzone",
    "supplieridentificationcode",
    "suppliercompanyid",
    "payeefinancialaccountid",
    "customername",
    "customerstreetname",
    "customercityname",
    "customerpostalzone",
    "customeridentificationcode",
    "customerendpointid",
    "buyerreference",
    "suppliercontactname",
    "suppliercontacttelephone",
    "suppliercontactelectronicmail",
    "billingreferenceid",
    "billingreferenceissuedate",
    "duedate",
})


def _override_path(data_dir: Path, wmai_id: int) -> Path:
    return Path(data_dir) / "overrides" / f"{int(wmai_id)}.json"


def load(data_dir: Path, wmai_id: int) -> dict:
    """Liefert das Override-Dict (oder leeres Dict wenn keines da)."""
    path = _override_path(data_dir, wmai_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("Override-Datei %s ist kein Dict — ignoriert", path)
            return {}
        return data
    except (OSError, json.JSONDecodeError):
        logger.exception("Override-Datei %s nicht lesbar", path)
        return {}


def save(data_dir: Path, wmai_id: int, values: dict) -> dict:
    """Schreibt Override-Werte. Filtert auf ALLOWED_KEYS + nicht-leere Strings."""
    cleaned: dict[str, str] = {}
    for k, v in (values or {}).items():
        if k not in ALLOWED_KEYS:
            continue
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        cleaned[k] = s[:500]  # Sicherheits-Cap

    path = _override_path(data_dir, wmai_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cleaned:
        # Leeres Override = Datei löschen (= reset)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        return {}
    path.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cleaned


def delete(data_dir: Path, wmai_id: int) -> bool:
    """Löscht die Override-Datei. True wenn etwas gelöscht wurde."""
    path = _override_path(data_dir, wmai_id)
    if path.exists():
        try:
            path.unlink()
            return True
        except OSError:
            logger.exception("Konnte Override-Datei %s nicht löschen", path)
            return False
    return False


def apply_to_invoice(data_dir: Path, wmai_id: int, invoice: dict) -> dict:
    """Merget gespeicherte Overrides ins Invoice-Header.

    Ändert das übergebene Dict NICHT in-place — gibt eine Kopie zurueck.
    Wenn keine Overrides gespeichert sind, wird das Original-Dict
    unverändert zurueckgegeben.
    """
    overrides = load(data_dir, wmai_id)
    if not overrides:
        return invoice
    out = dict(invoice)
    out["header"] = dict(invoice.get("header") or {})
    for k, v in overrides.items():
        if k in ALLOWED_KEYS:
            out["header"][k] = v
    # Korrigiert der Operator per Override nur die billingreferenceid (weil der
    # Auto-Fallback aus dem Zahlungs-Kommentar die falsche Original-Rechnung
    # traf), das mit aufgeloeste issuedate der FALSCHEN Rechnung nicht
    # dranlassen — sonst gemischtes BG-3-Paar. BT-26 ist optional.
    if "billingreferenceid" in overrides and "billingreferenceissuedate" not in overrides:
        out["header"]["billingreferenceissuedate"] = None
    logger.info(
        "Override für WMAI %s angewandt (%d Feld(er): %s)",
        wmai_id, len(overrides), ", ".join(overrides.keys()),
    )
    return out


def list_all(data_dir: Path) -> dict[int, dict]:
    """Listet alle vorhandenen Override-Dateien (für UI / Audit)."""
    root = Path(data_dir) / "overrides"
    if not root.exists():
        return {}
    result: dict[int, dict] = {}
    for f in root.glob("*.json"):
        try:
            wmai_id = int(f.stem)
        except ValueError:
            continue
        result[wmai_id] = load(data_dir, wmai_id)
    return result
