"""
slim/core_slim/archive_fs.py
----------------------------
Filesystem-Archive für erzeugte XRechnung-XMLs und KoSIT-Reports.

Layout:
  <data_dir>/xml/<YYYY>/<MM>/<zinv_number>.xml
  <data_dir>/xml/<YYYY>/<MM>/<zinv_number>.sha256
  <data_dir>/xml/<YYYY>/<MM>/<zinv_number>.kosit-report.xml   (optional)

Fehler-XMLs (Validierung nicht bestanden, zur Diagnose) liegen in einem
getrennten Parallelbaum — bewusst NICHT unter xml/, damit find_xml und die
Archiv-API sie nicht mit echten Archiven verwechseln:
  <data_dir>/xml_invalid/<YYYY>/<MM>/<zinv_number>.xml
  <data_dir>/xml_invalid/<YYYY>/<MM>/<zinv_number>.error.txt  (Fehlerklasse + Text)

Bei Konflikt (Re-Trigger auf bereits archivierte ZINV-Nummer im gleichen
Monat): bestehende Datei wird umbenannt zu <zinv_number>.<ts>.xml und
die neue Datei nimmt den Hauptnamen ein.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from slim.core_slim import xml_fakten
from slim.core_slim.clock import now_local

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
    n = now or now_local()
    return Path(data_dir) / "xml" / f"{n.year:04d}" / f"{n.month:02d}"


def _invalid_bucket(data_dir: Path, now: Optional[datetime] = None) -> Path:
    """Parallelbaum fuer Fehler-XMLs — bewusst NICHT unter ``xml/``, damit
    ``find_xml`` und die Archiv-API sie nicht mit echten Archiven verwechseln."""
    n = now or now_local()
    return Path(data_dir) / "xml_invalid" / f"{n.year:04d}" / f"{n.month:02d}"


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
    meta: Optional[dict] = None,
) -> dict:
    """Speichert XML + SHA256-Seitendatei + Metadaten (+ optional KoSIT-Report).

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

    meta_path = bucket / f"{safe}.meta.json"

    renamed: Optional[str] = None
    if xml_path.exists():
        ts = (now or now_local()).strftime("%Y%m%dT%H%M%S")
        rename_to = bucket / f"{safe}.{ts}.xml"
        n = 2
        while rename_to.exists():       # gleiche Sekunde: nie eine Version ueberschreiben
            rename_to = bucket / f"{safe}.{ts}-{n}.xml"
            n += 1
        try:
            xml_path.rename(rename_to)
            renamed = str(rename_to)
            # Pruefwert und Metadaten gehoeren zu IHRER Version - mit umbenennen,
            # sonst ueberschreibt die neue Version sie und die alte ist nicht
            # mehr als unveraendert nachweisbar.
            if sha_path.exists():
                old_digest = sha_path.read_text(encoding="utf-8").split()[0]
                rename_to.with_suffix(".sha256").write_text(
                    f"{old_digest}  {rename_to.name}\n", encoding="utf-8")
                sha_path.unlink()
            if meta_path.exists():
                meta_path.rename(rename_to.with_suffix(".meta.json"))
        except (OSError, IndexError):
            logger.exception(
                "Konnte existierende XML-Datei nicht umbenennen: %s", xml_path
            )

    xml_path.write_bytes(xml_bytes)
    digest = hashlib.sha256(xml_bytes).hexdigest()
    # SHA256-Format wie `sha256sum`: "<hex>  <filename>"
    sha_path.write_text(f"{digest}  {xml_path.name}\n", encoding="utf-8")
    _write_meta(meta_path, {**xml_fakten.lies(xml_bytes), **(meta or {}),
                            "status": "archiviert",
                            "archiviert_am": (now or now_local()).isoformat()})

    if kosit_path is not None:
        # KoSIT-Report ggf. bestehender Datei überlassen → bei Konflikt
        # ebenfalls versionieren (Reports gehoeren zu ihren XML-Datei).
        if kosit_path.exists():
            ts = (now or now_local()).strftime("%Y%m%dT%H%M%S")
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


def _write_meta(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_meta(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def meta_path(xml_path) -> Path:
    return Path(xml_path).with_suffix(".meta.json")


def mark_sent(xml_path, wmai_id: int, empfaenger: str, now: Optional[datetime] = None) -> None:
    """Nach geglücktem Anhängen: Status 'gesendet' mit Zeitpunkt und Empfänger."""
    p = meta_path(xml_path)
    data = _read_meta(p) or {}
    data.update(status="gesendet", angehaengt_am=(now or now_local()).isoformat(),
                wmai_id=wmai_id, empfaenger=empfaenger)
    _write_meta(p, data)


def norm_path(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


_SENT_CACHE: dict = {}


def sent_index(data_dir: Path) -> dict:
    """attach_ok-Einträge aller Audit-Dateien. Schlüssel: normalisierter
    xml_path und "sha:<sha256>"; Wert {angehaengt_am, wmai_id, sha256}.

    Massgeblich ist der Prüfwert: attach_ok nennt immer den Hauptnamen X.xml,
    nach einem Retry liegt dort aber eine andere Version. Zwischengespeichert,
    bis sich eine Audit-Datei ändert (Name, Größe, Zeitstempel)."""
    files = sorted(Path(data_dir).glob("audit-*.jsonl"))
    try:
        key = tuple((f.name, f.stat().st_size, f.stat().st_mtime_ns) for f in files)
    except OSError:
        key = None
    cached = _SENT_CACHE.get(norm_path(data_dir))
    if key is not None and cached and cached[0] == key:
        return cached[1]
    out: dict = {}
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event") != "attach_ok":
                continue
            details = e.get("details") or {}
            hit = {"angehaengt_am": e.get("ts"), "wmai_id": e.get("wmai_id"),
                   "sha256": details.get("sha256")}
            if details.get("xml_path"):
                out[norm_path(details["xml_path"])] = hit
            if details.get("sha256"):
                out["sha:" + str(details["sha256"]).lower()] = hit
    if key is not None:
        _SENT_CACHE[norm_path(data_dir)] = (key, out)
    return out


def _sha_of(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _hit(index: dict, xml_path: Path, sha: Optional[str]) -> Optional[dict]:
    if sha and index.get("sha:" + sha):
        return index["sha:" + sha]
    by_path = index.get(norm_path(xml_path))
    # Pfadtreffer nur, wenn das Protokoll keinen (anderen) Prüfwert nennt
    if by_path and not by_path.get("sha256"):
        return by_path
    return None


def ensure_meta(xml_path: Path, index: dict) -> dict:
    """Metadaten lesen; fehlen sie (Bestandsdatei), einmalig aus XML + Audit anlegen."""
    p = meta_path(xml_path)
    data = _read_meta(p)
    if data is not None:
        if data.get("status") == "archiviert" and index:
            # Anhängen geglückt, aber der Status konnte nicht geschrieben werden:
            # attach_ok mit gleichem Prüfwert belegt den Versand.
            hit = _hit(index, xml_path, _sha_of(xml_path))
            if hit:
                data.update(status="gesendet", angehaengt_am=hit.get("angehaengt_am"),
                            wmai_id=hit.get("wmai_id"))
                try:
                    _write_meta(p, data)
                except OSError:
                    logger.exception("Metadaten nicht schreibbar: %s", p)
        return data
    try:
        facts = xml_fakten.lies(Path(xml_path).read_bytes())
    except OSError:
        facts = {}
    hit = _hit(index, xml_path, _sha_of(xml_path))
    data = {**facts, "status": "gesendet" if hit else "archiviert", "nachgetragen": True}
    if hit:
        data.update(angehaengt_am=hit.get("angehaengt_am"), wmai_id=hit.get("wmai_id"))
    try:
        _write_meta(p, data)
    except OSError:
        logger.exception("Metadaten nicht schreibbar: %s", p)
    return data


def nachtragen(data_dir: Path) -> int:
    """Metadaten aller Bestandsdateien einmalig anlegen (beim Dienststart im
    Hintergrund), damit der erste Archivaufruf nach dem Update nicht alle
    Alt-XMLs im Request parsen muss. Liefert die Zahl nachgetragener Dateien."""
    root = Path(data_dir) / "xml"
    if not root.exists():
        return 0
    index = None
    count = 0
    for p in root.rglob("*.xml"):
        if p.name.endswith(".kosit-report.xml") or meta_path(p).exists():
            continue
        if index is None:
            index = sent_index(data_dir)
        ensure_meta(p, index)
        count += 1
    return count


def save_invalid_xml(
    data_dir: Path,
    zinv_number: str,
    xml_bytes: bytes,
    event: str,
    error_text: str,
    now: Optional[datetime] = None,
) -> dict:
    """Legt eine NICHT bestandene XML zu Diagnosezwecken unter
    ``<data_dir>/xml_invalid/<YYYY>/<MM>/`` ab, samt ``.error.txt``-Beiblatt
    (Fehlerklasse + Fehlertext).

    Bei Konflikt (gleiche Nummer, gleicher Monat) wird die bestehende XML wie
    im Erfolgsarchiv zu ``<stem>.<ts>.xml`` versioniert.

    Returns:
        {"xml_path": str, "error_path": str, "renamed_existing": str | None}
    """
    safe = _safe_name(zinv_number)
    bucket = _invalid_bucket(data_dir, now)
    bucket.mkdir(parents=True, exist_ok=True)

    xml_path = bucket / f"{safe}.xml"
    err_path = bucket / f"{safe}.error.txt"

    renamed: Optional[str] = None
    if xml_path.exists():
        ts = (now or now_local()).strftime("%Y%m%dT%H%M%S")
        rename_to = bucket / f"{safe}.{ts}.xml"
        try:
            xml_path.rename(rename_to)
            renamed = str(rename_to)
        except OSError:
            logger.exception(
                "Konnte existierende Fehler-XML nicht umbenennen: %s", xml_path
            )

    xml_path.write_bytes(xml_bytes)
    err_path.write_text(
        f"event: {event}\n{error_text}\n", encoding="utf-8"
    )

    return {
        "xml_path": str(xml_path),
        "error_path": str(err_path),
        "renamed_existing": renamed,
    }


def delete_invalid(data_dir: Path, zinv_number: str) -> int:
    """Entfernt alle Fehler-XMLs (inkl. versionierter und ``.error.txt``) einer
    ZINV-Nummer aus dem ``xml_invalid``-Baum. Fuer das Aufraeumen nach einem
    spaeter geglueckten Retry. No-Op wenn nichts vorhanden.

    Returns:
        Anzahl entfernter XML-Hauptdateien (ohne .error.txt).
    """
    safe = _safe_name(zinv_number)
    root = Path(data_dir) / "xml_invalid"
    if not root.exists():
        return 0
    removed = 0
    for p in root.rglob(f"*{safe}*"):
        if not p.is_file():
            continue
        try:
            p.unlink()
            if p.name.endswith(".xml"):
                removed += 1
        except OSError:
            logger.exception("Konnte Fehler-XML nicht loeschen: %s", p)
    return removed


# Versionierte Konflikt-Dateien: <stem>.<YYYYmmddTHHMMSS>.xml
_VERSIONED_SUFFIX = re.compile(r"\.\d{8}T\d{6}(-\d+)?\.xml$")


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
