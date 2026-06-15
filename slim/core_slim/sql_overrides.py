"""
slim/core_slim/sql_overrides.py
-------------------------------
Pro-Hotel-Override der SQL-Templates: ein DBA / IT-Verantwortlicher kann
die Mapping-Logik im UI anpassen, ohne den Repo-Quelltext anzufassen.

Layout:
  <data_dir>/sql_overrides/<name>.sql

Wenn dort eine Datei liegt, nutzt der Poller diese statt
``<repo>/sql/<name>``. Bei App-Updates bleibt der Override erhalten
(weil ``slim/data/`` gitignored ist und nicht von Updates angefasst wird).

Sicherheitsmodell (Defense-in-Depth):
  - Whitelist erlaubter Dateinamen
  - SQL muss mit ``SELECT`` oder ``WITH`` beginnen
  - Verbotene Keywords (UPDATE/DELETE/INSERT/DROP/CREATE/ALTER/
    TRUNCATE/GRANT/REVOKE/MERGE) werden in JEDEM per Semikolon
    getrennten Block geprueft
  - Die richtige Bindvariable (``:zinv_id`` bzw. ``:days``) muss
    enthalten sein, sonst kann der Caller nicht binden
  - Length-Cap 50 kB
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


ALLOWED_NAMES = {
    "invoice_header.sql": ":zinv_id",
    "invoice_lines.sql":  ":zinv_id",
    "invoice_tax.sql":    ":zinv_id",
    "invoice_totals.sql": ":zinv_id",
    "invoice_list.sql":   ":days",
}

_MAX_SQL_LEN = 50_000

_FORBIDDEN_KEYWORDS = (
    "UPDATE", "DELETE", "INSERT", "DROP", "CREATE", "ALTER",
    "TRUNCATE", "GRANT", "REVOKE", "MERGE", "EXECUTE", "CALL",
    "BEGIN", "DECLARE",
)


class SqlValidationError(Exception):
    """SQL-Override-Validierung fehlgeschlagen."""


def override_path(data_dir: Path, name: str) -> Path:
    if name not in ALLOWED_NAMES:
        raise SqlValidationError(f"Unbekannter Template-Name: {name}")
    return Path(data_dir) / "sql_overrides" / name


def load(data_dir: Path, name: str) -> Optional[str]:
    """Liefert den Override-Inhalt oder None wenn keiner existiert."""
    try:
        p = override_path(data_dir, name)
    except SqlValidationError:
        return None
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def save(data_dir: Path, name: str, content: str) -> None:
    """Validiert und speichert. Wirft SqlValidationError bei Verstoss."""
    validate(content, name)
    p = override_path(data_dir, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def delete(data_dir: Path, name: str) -> bool:
    """Loescht den Override (= zurueck auf Repo-Default).
    True wenn etwas geloescht wurde, sonst False.
    """
    try:
        p = override_path(data_dir, name)
    except SqlValidationError:
        return False
    if p.exists():
        try:
            p.unlink()
            return True
        except OSError:
            return False
    return False


def list_overrides(data_dir: Path) -> list[str]:
    """Liefert die Namen aller aktiven Overrides."""
    root = Path(data_dir) / "sql_overrides"
    if not root.exists():
        return []
    return sorted(
        f.name for f in root.glob("*.sql") if f.name in ALLOWED_NAMES
    )


def _strip_comments(sql: str) -> str:
    """Entfernt Inline- und Block-Kommentare aus dem SQL fuer die Pruefung
    (sonst koennte jemand ein DROP TABLE in einem Kommentar verstecken — das
    waere harmlos, aber unsere Pruefung wuerde es fluchend ablehnen)."""
    no_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    no_line = re.sub(r"--[^\n]*", " ", no_block)
    return no_line


def validate(sql: str, name: str) -> None:
    """Wirft SqlValidationError wenn das SQL nicht erlaubt ist."""
    if name not in ALLOWED_NAMES:
        raise SqlValidationError(f"Template-Name nicht erlaubt: {name}")
    if sql is None or not sql.strip():
        raise SqlValidationError("Leeres SQL.")
    if len(sql) > _MAX_SQL_LEN:
        raise SqlValidationError(
            f"SQL zu lang (max {_MAX_SQL_LEN} Bytes, eingegeben: {len(sql)})"
        )

    cleaned = _strip_comments(sql).strip()
    cleaned_upper = cleaned.upper()

    if not (cleaned_upper.startswith("SELECT") or cleaned_upper.startswith("WITH")):
        raise SqlValidationError(
            "SQL muss mit SELECT oder WITH beginnen — andere "
            "Statement-Arten sind nicht erlaubt."
        )

    # Per-Block-Pruefung gegen verbotene Keywords. Wir splitten an
    # Semikolons (auch wenn Oracle bei :NEW etc. mit Doppelpunkt arbeitet —
    # das stoert das Split nicht). Whole-word-Match per Regex damit
    # 'CREATEDATE' o.ae. nicht als 'CREATE' falsch positiv triggert.
    for block in re.split(r";\s*", cleaned_upper):
        block = block.strip()
        if not block:
            continue
        for kw in _FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{kw}\b", block):
                raise SqlValidationError(
                    f"Verbotenes Keyword '{kw}' gefunden — "
                    f"nur reine SELECT-Queries erlaubt."
                )

    # Bindvariable muss da sein, sonst kann der invoice_fetcher das
    # SQL nicht parameterisiert ausfuehren.
    expected_bind = ALLOWED_NAMES[name]
    if expected_bind not in sql:
        raise SqlValidationError(
            f"Pflicht-Bindvariable '{expected_bind}' fehlt im SQL — "
            f"sie ist die Schnittstelle zum Poller."
        )
