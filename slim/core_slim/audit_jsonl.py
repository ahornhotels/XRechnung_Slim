"""
slim/core_slim/audit_jsonl.py
-----------------------------
Append-only JSONL-Audit, eine Datei pro Monat.

Eine Zeile pro Aktion:
  {"ts": ISO8601-UTC, "event": <str>, "wmai_id": <int|None>,
   "zinv_number": <str|None>, "details": <obj>}

Datei: <data_dir>/audit-YYYY-MM.jsonl

Threadsafe per Lock für den Append-Pfad (Poller laeuft single-instance,
aber Retry-Endpoint kann parallel schreiben).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_DETAILS_MAX = 4000  # Bytes nach json.dumps — schuetzt vor unbounded Audit-Einträgen


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _audit_path(data_dir: Path, now: Optional[datetime] = None) -> Path:
    n = now or datetime.now(timezone.utc)
    return Path(data_dir) / f"audit-{n.year:04d}-{n.month:02d}.jsonl"


def _truncate_details(details: Any) -> Any:
    """Truncated den JSON-Dump der Details auf _DETAILS_MAX Bytes (UTF-8).

    Verhindert dass z.B. eine 500-Zeilen-KoSIT-Report-Liste die JSONL-
    Datei volllaufen laesst. Bei Truncation wird ein 'truncated' Marker
    angehängt. Nicht-JSON-serialisierbare Werte (bytes, datetime, …)
    werden via ``default=str`` umgewandelt.
    """
    if details is None:
        return None
    try:
        s = json.dumps(details, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        s = repr(details)[:_DETAILS_MAX]
        return {"raw": s, "truncated": True}
    if len(s.encode("utf-8")) <= _DETAILS_MAX:
        # Re-parse damit nicht-serialisierbare Werte als ihre str-Repraesentation
        # konsistent in der JSONL-Datei landen (statt als Python-Repr).
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return details
    truncated_s = s.encode("utf-8")[:_DETAILS_MAX].decode("utf-8", errors="ignore")
    return {"raw": truncated_s, "truncated": True}


def record(
    data_dir: Path,
    event: str,
    *,
    wmai_id: Optional[int] = None,
    zinv_number: Optional[str] = None,
    details: Any = None,
) -> dict:
    """Schreibt einen Audit-Eintrag in die aktuelle Monatsdatei.

    Returns: das geschriebene Dict (für Tests).
    """
    entry = {
        "ts": _now_iso(),
        "event": event,
        "wmai_id": wmai_id,
        "zinv_number": zinv_number,
        "details": _truncate_details(details),
    }
    path = _audit_path(Path(data_dir))
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _LOCK:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                # Auf einigen Filesystemen (z.B. Test-tmpfs) ist fsync no-op
                pass
    return entry


def record_safe(data_dir: Path, event: str, **kwargs) -> Optional[dict]:
    """Wie `record`, schluckt aber jede Exception (logt sie).

    Verhindert dass ein Audit-Schreibfehler die eigentliche Poller-
    Aktion zum Fehlschlagen bringt.
    """
    try:
        return record(data_dir, event, **kwargs)
    except Exception:
        logger.exception("Audit-Eintrag konnte nicht geschrieben werden (event=%s)", event)
        return None


def tail(data_dir: Path, n: int = 100, now: Optional[datetime] = None) -> list[dict]:
    """Liefert die letzten n Einträge aus der aktuellen Monatsdatei.

    Wenn die aktuelle Monatsdatei < n Einträge hat, wird die
    Vormonatsdatei mitgelesen (bis zu maximal 2 Dateien).

    Einträge, die nicht als JSON parsebar sind, werden übersprungen.
    """
    n = max(1, int(n))
    cur = now or datetime.now(timezone.utc)
    # Vormonat berechnen (auch ohne dateutil)
    prev_month = 12 if cur.month == 1 else cur.month - 1
    prev_year = cur.year - 1 if cur.month == 1 else cur.year
    # Reihenfolge: aelteste Datei zuerst, damit collected[-n:] die NEUESTEN
    # Einträge liefert (chronologisch korrekt).
    files = [
        Path(data_dir) / f"audit-{prev_year:04d}-{prev_month:02d}.jsonl",
        _audit_path(data_dir, cur),
    ]

    collected: list[dict] = []
    for path in files:
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        collected.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return collected[-n:]


def iter_events(data_dir: Path, year: int, month: int) -> Iterable[dict]:
    """Iteriert alle Einträge einer Monatsdatei. Yields Dicts."""
    path = Path(data_dir) / f"audit-{year:04d}-{month:02d}.jsonl"
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
