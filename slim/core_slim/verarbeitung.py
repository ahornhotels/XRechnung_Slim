"""
slim/core_slim/verarbeitung.py
------------------------------
Uebergang der alten Einstellung "Verarbeitung" (hotel.json mail_strategy='aus')
in den XRechnung-Schalter.

Die alte Oberflaeche konnte Slim pausieren (mail_strategy='aus'). Diese
Einstellung gibt es nicht mehr; ihr Wert liesse Slim nach dem Update still
stehen, waehrend der Schalter "EIN" zeigt. Darum:

- migriere_aus: Altwert 'aus' wird zum ausgeschalteten Trigger (gleiche
  Bedeutung "Pause"), danach mail_strategy='suite8'. Ist der Trigger nicht
  schaltbar (fehlt, nicht pruefbar, Recht fehlt), bleibt 'aus' - dann gilt das
  alte Verhalten weiter und die Statusanzeige warnt.
- aus_aufheben: beim Einschalten ueber den Schalter wird ein Altwert 'aus'
  ebenfalls aufgehoben, damit "EIN" auch wirklich verarbeitet.
"""
from __future__ import annotations

import logging
from pathlib import Path

from core.config_loader import CONFIG_DIR, atomic_write_json, load_json
from slim.core_slim import trigger_state

logger = logging.getLogger(__name__)


def _hotel_path() -> Path:
    return Path(CONFIG_DIR) / "hotel.json"


def aus_aufheben() -> bool:
    """mail_strategy 'aus' -> 'suite8'. True, wenn geaendert."""
    p = _hotel_path()
    cfg = load_json(p, default={}) or {}
    if str(cfg.get("mail_strategy") or "").strip().lower() != "aus":
        return False
    cfg["mail_strategy"] = "suite8"
    atomic_write_json(p, cfg)
    logger.info("Alte Einstellung Verarbeitung=aus aufgehoben (mail_strategy=suite8)")
    return True


def migriere_aus(conn) -> bool:
    """Altwert 'aus' in den ausgeschalteten Trigger ueberfuehren. True bei Erfolg."""
    st = trigger_state.read_state(conn)["state"]
    if st not in ("aktiv", "inaktiv"):
        return False
    if st == "aktiv":
        try:
            trigger_state.set_enabled(conn, False)
        except trigger_state.TriggerSchaltFehler as e:
            logger.warning("Verarbeitung=aus nicht in den Schalter uebernehmbar: %s", e)
            return False
    return aus_aufheben()
