"""
slim/jobs_slim/abrechnung.py
----------------------------
Monatsbericht fuer die Abrechnung (nur Kanal TBH).

Einmal im Monat, ab dem eingestellten Tag, geht ein kurzer Bericht ueber den
letzten abgelaufenen Monat an eine einstellbare Adresse: Betrieb, Zeitraum,
Anzahl der erstellten und der versendeten XRechnungen.

  Gezaehlt wird in Suite8 (nur SELECT):
    erstellt  = Mails des Zeitraums (Hoteldatum WMAI_FIDELIODATE), an denen
                eine XML haengt (WMAA) - das ist, was Slim angehaengt hat
    versendet = davon von Suite8 als gesendet gefuehrt (WMAI_SENT = 1)

  Versendet wird ueber Suite8: Slim hat keinen eigenen Mailversand und legt
  den Bericht als Textmail in die Mailwarteschlange (WTXT + WMAI). Der
  Suite8-Mailservice verschickt ihn wie jede andere Mail.

Einstellungen (hotel.json): abrechnung_email (leer = aus), abrechnung_tag
(Tag im Monat, 1-28). Was gesendet wurde, steht in <data>/abrechnung.json -
je Monat genau ein Bericht, auch wenn der Dienst am Stichtag nicht lief.
"""
from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from core.config_loader import load_hotel_config
from core.db_connector import get_connection
from modules.suite8_pattern import ist_rechnungsmail
from slim.core_slim import audit_jsonl
from slim.core_slim.clock import now_local

logger = logging.getLogger(__name__)

STAND_DATEI = "abrechnung.json"
TAG_STANDARD = 1

_ZAEHLEN_SQL = """
select count(*), count(case when m.wmai_sent = 1 then 1 end)
  from wmai m
 where m.wmai_fideliodate >= :von
   and m.wmai_fideliodate <  :bis
   and exists (select 1 from wmaa a
                where a.wmaa_wmai_id = m.wmai_id
                  and lower(a.wmaa_filename) like '%.xml')
"""

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class AbrechnungFehler(RuntimeError):
    pass


def letzter_monat(heute: date) -> tuple[date, date]:
    """(erster Tag des letzten abgelaufenen Monats, erster Tag des laufenden)."""
    bis = heute.replace(day=1)
    von = (bis - timedelta(days=1)).replace(day=1)
    return von, bis


def monat_von(text: str) -> tuple[date, date]:
    """'2026-10' -> (2026-10-01, 2026-11-01)."""
    m = re.fullmatch(r"(\d{4})-(\d{2})", text or "")
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise AbrechnungFehler("Monat als JJJJ-MM erwartet")
    von = date(int(m.group(1)), int(m.group(2)), 1)
    return von, (von + timedelta(days=32)).replace(day=1)


def schluessel(von: date) -> str:
    return f"{von.year:04d}-{von.month:02d}"


def _tag(cfg: dict) -> int:
    try:
        return min(28, max(1, int(cfg.get("abrechnung_tag") or TAG_STANDARD)))
    except (TypeError, ValueError):
        return TAG_STANDARD


def _empfaenger(cfg: dict) -> str:
    return str(cfg.get("abrechnung_email") or "").strip()


# ───────────────────────── Stand ─────────────────────────

def stand_lesen(data_dir: Path) -> dict:
    p = Path(data_dir) / STAND_DATEI
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("gesendet"), dict) else {"gesendet": {}}
    except (OSError, ValueError):
        return {"gesendet": {}}


def _stand_schreiben(data_dir: Path, stand: dict) -> None:
    p = Path(data_dir) / STAND_DATEI
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(stand, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def faellig(cfg: dict, heute: date, stand: dict) -> Optional[str]:
    """Monat (JJJJ-MM), fuer den jetzt ein Bericht zu senden ist, sonst None.
    Ab dem eingestellten Tag, und nur solange fuer den letzten Monat noch
    keiner gesendet wurde - so holt ein spaeter Start den Bericht nach."""
    if not _empfaenger(cfg) or heute.day < _tag(cfg):
        return None
    key = schluessel(letzter_monat(heute)[0])
    return None if key in (stand.get("gesendet") or {}) else key


# ───────────────────────── Suite8 ─────────────────────────

def zaehlen(conn, von: date, bis: date) -> dict:
    cur = conn.cursor()
    cur.execute(_ZAEHLEN_SQL, {"von": von, "bis": bis})
    row = cur.fetchone() or (0, 0)
    return {"erstellt": int(row[0] or 0), "versendet": int(row[1] or 0)}


def _wuss(conn, name: str) -> str:
    cur = conn.cursor()
    cur.execute("select max(wuss_value) from wuss where wuss_xcms_id = 0 and wuss_name = :n", {"n": name})
    row = cur.fetchone()
    return str(row[0]).strip() if row and row[0] else ""


def hausname(conn, cfg: dict) -> str:
    """Betriebsname aus Suite8 (Hoteleinstellung), sonst aus der Slim-Konfiguration."""
    try:
        name = _wuss(conn, "Hotelid")
    except Exception as e:
        logger.warning("Hausname aus Suite8 nicht lesbar: %s", e)
        name = ""
    return name or str(cfg.get("hotel_long_name") or cfg.get("hotel_code") or "").strip() or "unbekannt"


def absender(conn, cfg: dict) -> str:
    for wert in (cfg.get("absender_email"), cfg.get("seller_contact_email")):
        if wert and _EMAIL.fullmatch(str(wert).strip()):
            return str(wert).strip()
    try:
        wert = _wuss(conn, "Hotelemail")
    except Exception:
        wert = ""
    if _EMAIL.fullmatch(wert):
        return wert
    raise AbrechnungFehler("Kein Absender: Bitte unter Konfiguration → Haus die Absender-E-Mail eintragen.")


def _de(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def berichtstext(haus: str, von: date, bis: date, zahlen: dict, version: str, heute: date) -> tuple[str, str]:
    """(Betreff, Text). Der Betreff enthaelt bewusst weder 'Rechnung' noch
    'Invoice' noch eine Nummer mit '#': Die Mail darf keinen Trigger und kein
    Erkennungsmuster fuer Rechnungsmails treffen."""
    betreff = f"Slim Monatsbericht {von.month:02d}/{von.year} {haus}"[:250]
    text = "\r\n".join([
        "Monatsbericht XRechnung",
        "",
        f"Betrieb:  {haus}",
        f"Zeitraum: {_de(von)} bis {_de(bis - timedelta(days=1))}",
        "",
        f"Erstellte XRechnungen:   {zahlen['erstellt']}",
        f"Versendete XRechnungen:  {zahlen['versendet']}",
        "",
        "Erstellt: Rechnungsmails des Zeitraums (Hoteldatum), an die eine XRechnung angehängt wurde.",
        "Versendet: davon von Suite8 als gesendet geführt.",
        "",
        f"Slim {version or '?'} · Bericht vom {_de(heute)}",
        "",
    ])
    return betreff, text


def _mailtext_blob(text: str) -> bytes:
    """Mailtext so, wie Suite8 ihn ablegt: ZIP mit einem Eintrag 'stream',
    Klartext in Windows-1252 mit CRLF (WTXT_DOCFORMAT 1, WTXT_COMPRESSED 1)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("stream", text.encode("cp1252", errors="replace"))
    return buf.getvalue()


def mail_einstellen(conn, von: str, an: str, betreff: str, text: str) -> int:
    """Legt eine Textmail in die Suite8-Mailwarteschlange (nicht gesperrt).
    Eine Transaktion; bei Fehler Rollback. Liefert die WMAI_ID."""
    blob = _mailtext_blob(text)
    cur = conn.cursor()
    try:
        cur.execute("SELECT SEQ_WTXT.NEXTVAL FROM DUAL")
        wtxt_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO WTXT (WTXT_ID, WTXT_DATA, WTXT_DOCFORMAT, WTXT_SIZE, WTXT_COMPRESSED) "
            "VALUES (:id, :blob_data, 1, :blob_size, 1)",
            {"id": wtxt_id, "blob_data": blob, "blob_size": len(blob)})
        cur.execute("SELECT SEQ_WMAI.NEXTVAL FROM DUAL")
        wmai_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO WMAI
               (WMAI_ID, WMAI_BODY_WTXT_ID, WMAI_FIDELIODATE, WMAI_SENT, WMAI_NO_OF_ATTEMPTS,
                WMAI_SENDER, WMAI_TO, WMAI_SUBJECT, WMAI_BLOCKSEND, WMAI_READONLY, WMAI_SMS, WMAI_DRAFT)
               VALUES (:id, :body, NVL((SELECT MAX(TRUNC(WGBS_DATEVALUE)) FROM WGBS), TRUNC(SYSDATE)), 0, 0,
                       :sender, :empf, :betreff, 0, 0, 0, 0)""",
            {"id": wmai_id, "body": wtxt_id, "sender": von[:128], "empf": an[:2000], "betreff": betreff[:256]})
        conn.commit()
        return int(wmai_id)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


# ───────────────────────── Lauf ─────────────────────────

def vorschau(cfg: dict, heute: date, monat: Optional[str] = None) -> dict:
    """Zahlen und Text fuer einen Monat, ohne etwas zu senden (nur SELECT)."""
    von, bis = monat_von(monat) if monat else letzter_monat(heute)
    with get_connection() as conn:
        haus = hausname(conn, cfg)
        zahlen = zaehlen(conn, von, bis)
    betreff, text = berichtstext(haus, von, bis, zahlen, _version(), heute)
    return {"monat": schluessel(von), "von": von.isoformat(), "bis": (bis - timedelta(days=1)).isoformat(),
            "haus": haus, **zahlen, "betreff": betreff, "text": text}


def _version() -> str:
    try:
        return (Path(__file__).resolve().parents[2] / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def senden(data_dir: Path, cfg: dict, heute: date, monat: Optional[str] = None, von_hand: Optional[str] = None) -> dict:
    """Zaehlt, legt den Bericht in die Mailwarteschlange und merkt sich den
    Monat. von_hand = Benutzername bei Versand ueber die Oberflaeche."""
    an = _empfaenger(cfg)
    if not _EMAIL.fullmatch(an):
        raise AbrechnungFehler("Kein Empfänger: Bitte die E-Mail für den Abrechnungsbericht eintragen.")
    von, bis = monat_von(monat) if monat else letzter_monat(heute)
    if bis > heute.replace(day=1):
        raise AbrechnungFehler("Nur abgelaufene Monate lassen sich abrechnen.")
    with get_connection() as conn:
        haus = hausname(conn, cfg)
        zahlen = zaehlen(conn, von, bis)
        betreff, text = berichtstext(haus, von, bis, zahlen, _version(), heute)
        if ist_rechnungsmail(filename="", subject=betreff,
                             filename_pattern=cfg.get("suite8_recognize_filename_pattern", "") or "",
                             subject_pattern=cfg.get("suite8_recognize_subject_pattern", "") or ""):
            raise AbrechnungFehler("Der Betreff des Berichts trifft das Erkennungsmuster für Rechnungsmails "
                                   "und würde gesperrt. Bericht nicht gesendet.")
        wmai_id = mail_einstellen(conn, absender(conn, cfg), an, betreff, text)
    key = schluessel(von)
    eintrag = {"ts": now_local().isoformat(), "an": an, "haus": haus, "wmai_id": wmai_id,
               **zahlen, **({"von_hand": von_hand} if von_hand else {})}
    stand = stand_lesen(data_dir)
    stand["gesendet"][key] = eintrag
    _stand_schreiben(data_dir, stand)
    audit_jsonl.record_safe(Path(data_dir), "abrechnung_gesendet", wmai_id=wmai_id,
                            details={"monat": key, **eintrag})
    logger.info("Abrechnungsbericht %s an %s eingestellt (WMAI %s)", key, an, wmai_id)
    return {"monat": key, **eintrag}


def run_once(data_dir: Path, heute: Optional[date] = None) -> dict:
    """Zeitgesteuerter Aufruf: sendet, wenn ein Bericht faellig ist."""
    heute = heute or now_local().date()
    try:
        cfg = load_hotel_config() or {}
    except Exception:
        return {"gesendet": False, "grund": "keine Konfiguration"}
    key = faellig(cfg, heute, stand_lesen(data_dir))
    if not key:
        return {"gesendet": False}
    try:
        return {"gesendet": True, **senden(data_dir, cfg, heute, monat=key)}
    except Exception as e:
        logger.exception("Abrechnungsbericht %s fehlgeschlagen", key)
        audit_jsonl.record_safe(Path(data_dir), "abrechnung_fehler",
                                details={"monat": key, "error": str(e)[:400]})
        return {"gesendet": False, "fehler": str(e)[:400]}
