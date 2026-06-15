"""
slim/core_slim/archive_fs.py
----------------------------
Filesystem-Archive für erzeugte XRechnung-XMLs und KoSIT-Reports.

Layout:
  <data_dir>/xml/<YYYY>/<MM>/<zinv_number>.xml
  <data_dir>/xml/<YYYY>/<MM>/<zinv_number>.sha256
  <data_dir>/xml/<YYYY>/<MM>/<zinv_number>.kosit-report.xml   (optional)

Bei Konflikt (Re-Trigger auf bereits archivierte ZINV-Nummer im gleichen
Monat): bestehende Datei wird umbenannt zu <zinv_number>.<ts>.xml und
die neue Datei nimmt den Hauptnamen ein.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Windows-reservierte Dateinamen (Case-Insensitive matching). Datei mit
# einem dieser Namen ist nicht erstellbar / liefert beim open() Fehler.
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_NAME_WHITELIST = re.compile(r"[^A-Za-z0-9._-]")
_NAME_MAX_LEN = 64


def _bucket(data_dir: Path, now: Optional[datetime] = None) -> Path:
    n = now or datetime.now(timezone.utc)
    return Path(data_dir) / "xml" / f"{n.year:04d}" / f"{n.month:02d}"


def _safe_name(name: str) -> str:
    """Whitelist-Filter für Dateinamen.

    ZINV-Nummer kommt zwar aus Suite8 (Regex-extrahiert), aber das Pattern
    ist user-konfigurierbar — wir trauen dem Input deshalb nicht und
    erlauben nur ``[A-Za-z0-9._-]``. Zusaetzlich Reserved-Names (CON/PRN/etc.)
    blocken, sonst crasht write_bytes auf Windows.
    """
    cleaned = _NAME_WHITELIST.sub("_", (name or "").strip())
    # Fuehrende Punkte (..) und Trailing-Punkt/Spaces blocken
    cleaned = cleaned.strip(". ")
    cleaned = cleaned[:_NAME_MAX_LEN]
    if not cleaned:
        return "unknown"
    if cleaned.upper() in _WINDOWS_RESERVED:
        return f"_{cleaned}"
    return cleaned


def save_xml(
    data_dir: Path,
    zinv_number: str,
    xml_bytes: bytes,
    kosit_report: Optional[bytes] = None,
    now: Optional[datetime] = None,
    filename: Optional[str] = None,
) -> dict:
    """Speichert XML + SHA256-Seitendatei (+ optional KoSIT-Report).

    Args:
        filename: Fertiger Dateiname aus dem Anhang-Template (z.B.
            "XRechnung_144853.xml"). Wenn gesetzt, tragen alle erzeugten
            Dateien dessen Stem; ohne wird die zinv_number verwendet.
            Der Name ist user-konfigurierbar — _safe_name filtert ihn.

    Returns:
        {"xml_path": str, "sha256": str, "kosit_path": str | None,
         "renamed_existing": str | None}
    """
    if filename:
        stem = filename[:-4] if filename.lower().endswith(".xml") else filename
        safe = _safe_name(stem)
    else:
        safe = _safe_name(zinv_number)
    bucket = _bucket(data_dir, now)
    bucket.mkdir(parents=True, exist_ok=True)

    xml_path = bucket / f"{safe}.xml"
    sha_path = bucket / f"{safe}.sha256"
    kosit_path = bucket / f"{safe}.kosit-report.xml" if kosit_report is not None else None

    renamed: Optional[str] = None
    if xml_path.exists():
        ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
        rename_to = bucket / f"{safe}.{ts}.xml"
        try:
            xml_path.rename(rename_to)
            renamed = str(rename_to)
        except OSError:
            logger.exception(
                "Konnte existierende XML-Datei nicht umbenennen: %s", xml_path
            )

    xml_path.write_bytes(xml_bytes)
    digest = hashlib.sha256(xml_bytes).hexdigest()
    # SHA256-Format wie `sha256sum`: "<hex>  <filename>"
    sha_path.write_text(f"{digest}  {xml_path.name}\n", encoding="utf-8")

    if kosit_path is not None:
        # KoSIT-Report ggf. bestehender Datei überlassen → bei Konflikt
        # ebenfalls versionieren (Reports gehoeren zu ihren XML-Datei).
        if kosit_path.exists():
            ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
            try:
                kosit_path.rename(bucket / f"{safe}.{ts}.kosit-report.xml")
            except OSError:
                logger.exception(
                    "Konnte existierenden KoSIT-Report nicht umbenennen: %s", kosit_path
                )
        kosit_path.write_bytes(kosit_report)

    return {
        "xml_path": str(xml_path),
        "sha256": digest,
        "kosit_path": str(kosit_path) if kosit_path else None,
        "renamed_existing": renamed,
    }


# Versionierte Konflikt-Dateien: <stem>.<YYYYmmddTHHMMSS>.xml
_VERSIONED_SUFFIX = re.compile(r"\.\d{8}T\d{6}\.xml$")


def find_xml(data_dir: Path, zinv_number: str) -> list[Path]:
    """Sucht alle archivierten Hauptdateien (ohne .<ts>.xml-Versionen) für eine ZINV-Nummer.

    Matcht per Substring, damit auch template-benannte Dateien
    (z.B. "XRechnung_144853.xml") gefunden werden. KoSIT-Reports und
    versionierte Konflikt-Dateien sind ausgenommen.

    Nuetzlich für Audit-Prüfungen / UI. Liefert sortierte Liste (neueste zuerst).
    """
    safe = _safe_name(zinv_number)
    root = Path(data_dir) / "xml"
    if not root.exists():
        return []
    matches = sorted(root.rglob(f"*{safe}*.xml"), reverse=True)
    return [
        p for p in matches
        if p.is_file()
        and not p.name.endswith(".kosit-report.xml")
        and not _VERSIONED_SUFFIX.search(p.name)
    ]
