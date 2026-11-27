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
from core.db_connector import get_connection
from slim.core_slim import trigger_state

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


# ─────────────────── Trigger in Suite8 gegen den Standard pruefen ───────────────────

def _zerlegen(sql: str) -> tuple[str, list]:
    """(Code ohne Kommentare, Textkonstanten). Die Konstanten stehen im Code
    als Platzhalter '?' - so veraendert ein Kommentarzeichen in einem Muster
    nichts, und Gross-/Kleinschreibung zaehlt nur dort, wo sie wirkt."""
    code, texte, i, n = [], [], 0, len(sql)
    while i < n:
        c, zwei = sql[i], sql[i:i + 2]
        if c == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and sql[j + 1:j + 2] == "'":
                    j += 2
                    continue
                if sql[j] == "'":
                    break
                j += 1
            texte.append(sql[i + 1:j])
            code.append(" '?' ")
            i = j + 1
        elif zwei == "--":
            j = sql.find("\n", i)
            i = n if j < 0 else j
        elif zwei == "/*":
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            code.append(c)
            i += 1
    return "".join(code), texte


def _norm(sql: str) -> tuple[str, tuple]:
    code, texte = _zerlegen(sql or "")
    return re.sub(r"\s+", "", code).lower().rstrip("/"), tuple(texte)


def _standard_rumpf(fn_pat: str, sub_pat: str) -> str:
    sql = build_block_trigger_sql(fn_pat, sub_pat)
    return sql[sql.index("DECLARE"):]


_PRUEFUNG_IM_STANDARD = re.compile(
    r"IF NVL\(:NEW\.WMAI_SENT, 0\) = 0 THEN\s+IF (.*?) THEN\s+-- Idempotenz", re.S)


def trigger_abweichungen(event: str, body: str, fn_pat: str, sub_pat: str) -> list:
    """Was am Trigger in Suite8 nicht zum Standard passt, als Klartext-Liste.
    Leer = entspricht dem Standard zu den eingestellten Mustern."""
    standard = _standard_rumpf(fn_pat, sub_pat)
    if _norm(body) == _norm(standard) and set((event or "").upper().split()) - {"OR"} == {"INSERT", "UPDATE"}:
        return []
    out = []
    worte = set((event or "").upper().split()) - {"OR"}
    if worte and worte != {"INSERT", "UPDATE"}:
        out.append(f"Der Trigger läuft bei „{(event or '').upper()}“, der Standard bei INSERT OR UPDATE "
                   "(Anlegen der Mail und Änderung von Versuchszähler oder Gesendet-Kennzeichen).")

    code, _ = _zerlegen(body or "")
    tabellen = []
    for m in re.finditer(r"\bfrom\s+(.+?)(?=\bwhere\b|\bgroup\b|\border\b|;|\)|$)", code, re.S | re.I):
        for teil in m.group(1).split(","):
            name = (teil.split() or [""])[0].upper()
            if re.fullmatch(r"[A-Z][A-Z0-9_$#.]*", name) and name not in ("WMAA", "DUAL") and name not in tabellen:
                tabellen.append(name)
    if tabellen:
        out.append("Der Trigger liest zusätzlich aus " + ", ".join(tabellen) + ". Der Standard prüft nur, "
                   "ob schon eine XML an der Mail hängt (WMAA). Der Trigger filtert also selbst, "
                   "welche Rechnungsmails gesperrt werden.")
    abfragen = len(re.findall(r"\bselect\b", code, re.I))
    if abfragen > 1 and not re.search(r"\bexception\b", code, re.I):
        out.append(f"Er enthält {abfragen} Abfragen ohne Fehlerbehandlung. Liefert eine davon keine oder "
                   "mehrere Zeilen, bricht Suite8 das Anlegen der Mail mit einem Oracle-Fehler ab.")
    m = _PRUEFUNG_IM_STANDARD.search(standard)
    if m:
        soll_code, soll_texte = _norm(m.group(1))
        ist_code, ist_texte = _norm(body)
        if soll_code not in ist_code or any(t not in ist_texte for t in soll_texte):
            out.append("Die Erkennung der Rechnungsmail im Trigger weicht von den in Slim eingestellten "
                       "Mustern ab. Sperrt der Trigger Mails, die Slim nicht als Rechnung erkennt, "
                       "bleiben sie hängen.")
    if not out:
        out.append("Der Text des Triggers weicht vom Standard ab.")
    return out


_FN, _SUB = "@@DATEINAME@@", "@@BETREFF@@"


def muster_im_trigger(event: str, body: str):
    """Ist der Trigger ein Standard-Trigger von Slim - gleich fuer welche
    Muster -, liefert das die Muster, die in ihm stehen (Oracle-Schreibweise):
    {"dateiname", "betreff"}, je None wenn nicht enthalten. Sonst None: Der
    Trigger wurde von Hand veraendert."""
    if set((event or "").upper().split()) - {"OR"} != {"INSERT", "UPDATE"}:
        return None
    ist_code, ist_texte = _norm(body)
    for fn, sub in ((_FN, ""), ("", _SUB), (_FN, _SUB), ("", "")):
        soll_code, soll_texte = _norm(_standard_rumpf(fn, sub))
        if soll_code != ist_code or len(soll_texte) != len(ist_texte):
            continue
        gefunden = {"dateiname": None, "betreff": None}
        passt = True
        for soll, ist in zip(soll_texte, ist_texte):
            if soll == _FN:
                gefunden["dateiname"] = ist.replace("''", "'")
            elif soll == _SUB:
                gefunden["betreff"] = ist.replace("''", "'")
            elif soll != ist:
                passt = False
                break
        if not passt:
            continue
        if not fn and not sub:          # Trigger ohne eingestelltes Muster: fester Vorgabewert
            gefunden["dateiname"] = "Folio.*\\.pdf$"
        return gefunden
    return None


@router.get("/trigger-pruefung")
def get_trigger_pruefung() -> dict:
    """Liest den Trigger aus Suite8 (nur SELECT) und vergleicht ihn mit dem
    Standard zu den eingestellten Mustern. angepasst: True/False, oder None,
    wenn der Trigger fehlt oder nicht lesbar ist. muster_veraltet: True, wenn
    es der unveraenderte Standard-Trigger ist, aber mit anderen Mustern als
    den jetzt eingestellten (Muster geaendert, Trigger nicht neu ausgefuehrt)."""
    hotel = load_json(CONFIG_DIR / "hotel.json", default={}) or {}
    fn_pat = hotel.get("suite8_recognize_filename_pattern", "") or ""
    sub_pat = hotel.get("suite8_recognize_subject_pattern", "") or ""
    try:
        with get_connection() as conn:
            q = trigger_state.read_source(conn)
    except Exception as e:
        return {"state": "nicht_pruefbar", "angepasst": None, "muster_veraltet": None, "abweichungen": [],
                "quelltext": None, "error": str(e)[:500]}
    if not q.get("body"):
        return {"state": q["state"], "angepasst": None, "muster_veraltet": None, "abweichungen": [],
                "quelltext": None, "error": q.get("error")}
    ab = trigger_abweichungen(q.get("event") or "", q["body"], fn_pat, sub_pat)
    im_trigger = muster_im_trigger(q.get("event") or "", q["body"]) if ab else None
    out = {"state": q["state"], "angepasst": bool(ab) and im_trigger is None,
           "muster_veraltet": im_trigger is not None, "abweichungen": ab,
           "quelltext": q["body"], "error": None}
    if im_trigger is not None:
        out["muster_im_trigger"] = im_trigger
        out["muster_eingestellt"] = {"dateiname": _python_to_oracle_regex(fn_pat) or None,
                                     "betreff": _python_to_oracle_regex(sub_pat) or None}
    return out


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
