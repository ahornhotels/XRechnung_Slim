"""
slim/api_slim/trigger_sql.py
----------------------------
Auch NACH dem Setup-Abschluss erreichbar: liefert das BLOCKSEND-Trigger-SQL
zum Kopieren an den DBA.

Hintergrund: der Wizard zeigt den Trigger einmal in Schritt 6, aber
viele Hotels brauchen das SQL spaeter nochmal (DBA war beim Setup
nicht erreichbar, Re-Deploy, andere Pattern-Konfig).
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter

from core.config_loader import CONFIG_DIR, load_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["trigger"])


def _python_to_oracle_regex(pattern: str) -> str:
    """Konvertiert Python-spezifische Regex-Syntax in Oracle-POSIX-Format.

    Oracle's REGEXP_LIKE versteht weder das Python-Named-Group-Format
    ``(?P<name>...)`` noch Non-Capturing-Groups ``(?:...)`` und matched
    dann gar nichts. Bei unseren Patterns sind beide nur fuer die
    Python-seitige Extraktion relevant - der Trigger braucht nur einen
    booleschen Match, normale Capture-Groups sind dafuer aequivalent.

    Konversion:
      ``(?P<zinv_number>\\d+)``            ->  ``(\\d+)``
      ``(?P<zinv_id>\\d+)``                ->  ``(\\d+)``
      ``(?:Ihre Rechnung|Invoice number)`` ->  ``(Ihre Rechnung|Invoice number)``
    """
    converted = re.sub(r"\(\?P<\w+>", "(", pattern)
    return converted.replace("(?:", "(")


def build_block_trigger_sql(fn_pat: str, sub_pat: str) -> str:
    """Baut das vollstaendige BLOCKSEND-Trigger-SQL inkl. Idempotenz-Guard.

    Gemeinsamer Generator fuer beide Endpunkte (Post-Setup ``trigger_sql.py``
    und Wizard ``setup_api.py``), damit das ausgespielte SQL identisch ist und
    nicht auseinanderdriftet.

    ``fn_pat`` / ``sub_pat`` sind die Python-Patterns aus ``hotel.json``; sie
    werden hier in Oracle-POSIX-Syntax umgewandelt (Named-Groups,
    Non-Capturing-Groups) und einfach-Quotes fuers Inline-SQL escaped.

    Idempotenz-Guard: der Trigger setzt ``BLOCKSEND`` nur, wenn an der Mail
    noch KEIN XRechnung-XML haengt. Das verhindert eine Re-Block-Endlosschleife,
    falls der Suite8-Mailspooler beim Versand zuerst ``WMAI_NO_OF_ATTEMPTS``
    erhoeht, waehrend ``WMAI_SENT`` noch 0 ist (der Betreff matcht dann
    weiterhin, aber das XML haengt bereits → kein erneuter Block).
    """
    fn_pat_ora = _python_to_oracle_regex(fn_pat)
    sub_pat_ora = _python_to_oracle_regex(sub_pat)

    safe_fn = fn_pat_ora.replace("'", "''")
    safe_sub = sub_pat_ora.replace("'", "''")

    if fn_pat and not sub_pat:
        check = (
            ":NEW.WMAI_ATTACHMENT_FILE_NAME IS NOT NULL\n"
            f"     AND REGEXP_LIKE(:NEW.WMAI_ATTACHMENT_FILE_NAME, '{safe_fn}', 'i')"
        )
    elif sub_pat and not fn_pat:
        check = (
            ":NEW.WMAI_SUBJECT IS NOT NULL\n"
            f"     AND REGEXP_LIKE(:NEW.WMAI_SUBJECT, '{safe_sub}', 'i')"
        )
    elif fn_pat and sub_pat:
        check = (
            "(\n"
            "        (:NEW.WMAI_ATTACHMENT_FILE_NAME IS NOT NULL\n"
            f"         AND REGEXP_LIKE(:NEW.WMAI_ATTACHMENT_FILE_NAME, '{safe_fn}', 'i'))\n"
            "     OR (:NEW.WMAI_SUBJECT IS NOT NULL\n"
            f"         AND REGEXP_LIKE(:NEW.WMAI_SUBJECT, '{safe_sub}', 'i'))\n"
            "   )"
        )
    else:
        check = (
            ":NEW.WMAI_ATTACHMENT_FILE_NAME IS NOT NULL\n"
            "     AND REGEXP_LIKE(:NEW.WMAI_ATTACHMENT_FILE_NAME, 'Folio.*\\.pdf$', 'i')"
        )

    return f"""\
-- Suite8 XRechnung Slim - WMAI BLOCKSEND-Trigger
-- Bitte als V8LIVE oder Suite8-DBA EINMALIG ausfuehren.
-- Pattern aus aktueller hotel.json (Python-Named-Groups
-- in Oracle-POSIX-Syntax umgewandelt):
--   filename (Python): {fn_pat or '<leer>'}
--   subject  (Python): {sub_pat or '<leer>'}
--   filename (Oracle): {fn_pat_ora or '<leer>'}
--   subject  (Oracle): {sub_pat_ora or '<leer>'}
CREATE OR REPLACE TRIGGER WMAI_XRECHNUNG_BLOCK
BEFORE INSERT OR UPDATE OF WMAI_NO_OF_ATTEMPTS, WMAI_SENT
ON WMAI
FOR EACH ROW
DECLARE
  v_has_xml NUMBER := 0;
BEGIN
  -- Robust gegen NULL: wenn WMAI_SENT NICHT explizit auf 1 steht,
  -- nehmen wir die Mail in den Block-Check. Das verhindert das stille
  -- Aussetzen, wenn Suite8 die Spalte beim INSERT mit NULL anlegt.
  IF NVL(:NEW.WMAI_SENT, 0) = 0 THEN
    IF {check} THEN
      -- Idempotenz-Guard: nicht erneut blocken, wenn bereits ein
      -- XRechnung-XML an der Mail haengt (schuetzt gegen Re-Block,
      -- falls der Mailspooler NO_OF_ATTEMPTS erhoeht waehrend SENT=0).
      SELECT COUNT(*) INTO v_has_xml
        FROM WMAA
       WHERE WMAA_WMAI_ID = :NEW.WMAI_ID
         AND LOWER(WMAA_FILENAME) LIKE '%.xml';
      IF v_has_xml = 0 THEN
        :NEW.WMAI_BLOCKSEND := 1;
      END IF;
    END IF;
  END IF;
END;
/"""


@router.get("/trigger-sql")
def get_trigger_sql() -> dict:
    """Liefert das BLOCKSEND-Trigger-SQL basierend auf dem aktuell
    konfigurierten Pattern. Auch nach Setup-Abschluss erreichbar.

    Hat KEINE Auth (Slim-Konvention: bind 127.0.0.1).
    """
    hotel = load_json(CONFIG_DIR / "hotel.json", default={}) or {}
    fn_pat = hotel.get("suite8_recognize_filename_pattern", "") or ""
    sub_pat = hotel.get("suite8_recognize_subject_pattern", "") or ""

    sql = build_block_trigger_sql(fn_pat, sub_pat)
    return {
        "sql": sql,
        "has_filename_pattern": bool(fn_pat),
        "has_subject_pattern": bool(sub_pat),
        "filename_pattern": fn_pat,
        "subject_pattern": sub_pat,
    }
