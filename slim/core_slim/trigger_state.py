"""
slim/core_slim/trigger_state.py
-------------------------------
Zustand des Suite8-Triggers WMAI_XRECHNUNG_BLOCK lesen und schalten.

Der Zustand wird nie in Slim gespeichert, sondern immer aus der Datenbank
gelesen (ALL_TRIGGERS). So zeigt die Oberflaeche auch dann die Wahrheit, wenn
der DBA den Trigger von Hand schaltet oder neu anlegt.

Zustaende:
  aktiv           - Trigger vorhanden und ENABLED
  inaktiv         - Trigger vorhanden und DISABLED
  fehlt           - WMAI gehoert Slims Benutzer, aber der Trigger existiert nicht
  nicht_pruefbar  - Datenbankfehler oder keine Sicht (WMAI gehoert einem anderen
                    Benutzer und der Trigger ist nicht sichtbar). Bewusst NICHT
                    "fehlt", damit niemand einen vorhandenen Trigger neu anlegt.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

TRIGGER_NAME = "WMAI_XRECHNUNG_BLOCK"
_TABLE = "WMAI"
_IDENT = re.compile(r"^[A-Z0-9_$#]{1,128}$")


class TriggerSchaltFehler(RuntimeError):
    """Schalten nicht moeglich (Trigger fehlt, nicht pruefbar, Oracle-Fehler)."""


def _wmai_owner(cur, user: str) -> Optional[str]:
    cur.execute("SELECT owner FROM all_tables WHERE table_name = :t", {"t": _TABLE})
    owners = [r[0] for r in cur.fetchall()]
    if user in owners:
        return user
    cur.execute(
        "SELECT table_owner FROM all_synonyms WHERE synonym_name = :t "
        "AND owner IN (:u, 'PUBLIC') ORDER BY DECODE(owner, 'PUBLIC', 1, 0)",
        {"t": _TABLE, "u": user},
    )
    row = cur.fetchone()
    if row and row[0]:
        return row[0]
    return owners[0] if len(owners) == 1 else None


def read_state(conn) -> dict:
    out = {"state": "nicht_pruefbar", "owner": None, "user": None,
           "grant_sql": None, "error": None}
    try:
        cur = conn.cursor()
        cur.execute("SELECT USER FROM dual")
        row = cur.fetchone()
        user = str(row[0]) if row and row[0] else None
        out["user"] = user
        if not user:
            out["error"] = "Datenbankbenutzer nicht ermittelbar"
            return out
        owner = _wmai_owner(cur, user)
        cur.execute(
            "SELECT owner, status FROM all_triggers WHERE trigger_name = :n "
            "AND table_name = :t AND table_owner = :o",
            {"n": TRIGGER_NAME, "t": _TABLE, "o": owner or user},
        )
        trig = cur.fetchone()
        if trig:
            t_owner, status = str(trig[0]), str(trig[1] or "").upper()
            out["owner"] = t_owner
            out["state"] = {"ENABLED": "aktiv", "DISABLED": "inaktiv"}.get(status, "nicht_pruefbar")
            if t_owner != user:
                out["grant_sql"] = f"GRANT ALTER ANY TRIGGER TO {user};"
        elif owner == user:
            out["state"] = "fehlt"
        else:
            out["error"] = ("Trigger nicht sichtbar - WMAI gehoert einem anderen "
                            "Datenbankbenutzer")
    except Exception as e:  # jede DB-Stoerung = nicht pruefbar, nie "fehlt"
        logger.warning("Triggerzustand nicht lesbar: %s", e)
        out["state"] = "nicht_pruefbar"
        out["error"] = str(e)[:500]
    return out


def set_enabled(conn, enabled: bool) -> dict:
    st = read_state(conn)
    if st["state"] == "fehlt":
        raise TriggerSchaltFehler("Trigger fehlt - bitte zuerst das Trigger-SQL vom DBA ausfuehren lassen")
    if st["state"] not in ("aktiv", "inaktiv"):
        raise TriggerSchaltFehler("Triggerzustand nicht pruefbar" + (f": {st['error']}" if st["error"] else ""))
    owner = st["owner"] or ""
    if not _IDENT.match(owner):
        raise TriggerSchaltFehler(f"Ungueltiger Besitzername des Triggers: {owner!r}")
    sql = f'ALTER TRIGGER "{owner}"."{TRIGGER_NAME}" {"ENABLE" if enabled else "DISABLE"}'
    try:
        conn.cursor().execute(sql)
    except Exception as e:
        raise TriggerSchaltFehler(str(e)[:500]) from e
    return read_state(conn)
