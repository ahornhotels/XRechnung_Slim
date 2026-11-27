"""
modules/xrechnung_filter.py
---------------------------
Welche Rechnung bekommt eine XRechnung? Je Haus einstellbar (hotel.json):

  xrechnung_karteitypen    Karteitypen des Rechnungsempfaengers, die eine
                           XRechnung bekommen. Leer = alle.
  xrechnung_mindestbetrag  Rechnungen (380) mit Brutto unter diesem Betrag
                           bekommen keine. Leer oder 0 = keine Grenze.

Karteityp ist die Suite8-Kategorie der Kartei (XCMS_XCCA_ID -> XCCA), als
XCCA_INTERNALCATEGORY: 1 Firma, 2 Reisebuero/Agentur, 3 Reservierungsstelle,
4 Individuell. XCMS_TYPE allein reicht nicht - Firma, Reisebuero und
Reservierungsstelle haben dort alle den Wert 1. Die XCCA_ID taugt auch nicht,
sie kann je Haus abweichen.

Der Suite8-Trigger sperrt weiterhin JEDE Rechnungsmail; entschieden wird hier,
nachdem die Rechnung gelesen ist. Was ausgefiltert wird, gibt der Poller
sofort frei (Suite8 verschickt nur das PDF) und schreibt es ins Protokoll -
anders als ein Filter im Trigger bleibt jede Entscheidung nachvollziehbar.

Vorrang hat der erklaerte Wille des Empfaengers: Mit DXR-Mitgliedschaft
(Leitweg-ID bzw. Kaeuferreferenz) oder Nur-XML-Mitgliedschaft bekommt er immer
eine XRechnung.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from core.db_connector import get_connection

logger = logging.getLogger(__name__)

# Bezeichnungen je XCCA_INTERNALCATEGORY, falls XCCA keine liefert.
KARTEITYP_NAMEN: dict[str, str] = {
    "1": "Firma", "2": "Reisebüro/Agentur", "3": "Reservierungsstelle", "4": "Individuell",
}

_KATEGORIE_SQL = """
select c.xcca_internalcategory
  from zinv i, xcms x, xcca c
 where i.zinv_id = :zinv_id
   and x.xcms_id = i.zinv_xcms_id
   and c.xcca_id = x.xcms_xcca_id
"""

_AUSWAHL_SQL = """
select c.xcca_internalcategory, c.xcca_longdesc, nvl(c.xcca_inactive, 0),
       (select count(*) from xcms x where x.xcms_xcca_id = c.xcca_id)
  from xcca c
 order by c.xcca_internalcategory, nvl(c.xcca_inactive, 0), c.xcca_id
"""


def _typ(wert) -> Optional[str]:
    """Kategorie als Text ('1'); Oracle liefert NUMBER je nach Treiber als int,
    float oder Decimal. Leer/unlesbar = None."""
    if wert is None or str(wert).strip() == "":
        return None
    try:
        return str(int(Decimal(str(wert).strip())))
    except (InvalidOperation, ValueError):
        return None


def _betrag(wert) -> Optional[Decimal]:
    if wert is None or str(wert).strip() == "":
        return None
    try:
        return Decimal(str(wert).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _de(betrag: Decimal) -> str:
    return f"{betrag:.2f}".replace(".", ",")


def typname(typ: str) -> str:
    return KARTEITYP_NAMEN.get(typ) or f"Typ {typ}"


def karteityp_der_rechnung(cur, zinv_id: int) -> Optional[str]:
    """Karteityp (XCCA_INTERNALCATEGORY) des Rechnungsempfaengers. Bei
    Datenbankfehler oder fehlender Zuordnung None - dann filtert die Regel
    nicht (lieber eine XRechnung zu viel als still nur PDF)."""
    try:
        cur.execute(_KATEGORIE_SQL, {"zinv_id": zinv_id})
        row = cur.fetchone()
        return _typ(row[0]) if row else None
    except Exception as e:
        logger.warning("Karteityp fuer ZINV %s nicht lesbar: %s", zinv_id, e)
        return None


def ausschlussgrund(inv: dict, cfg: dict) -> Optional[dict]:
    """None = die Rechnung bekommt eine XRechnung. Sonst
    {"regel": "karteityp"|"mindestbetrag", "text": ..., ...} - dann geht die
    Mail ohne XRechnung hinaus."""
    cfg = cfg or {}
    header = inv.get("header") or {}
    if inv.get("kaeuferreferenz_mitglied") or inv.get("xml_only") == "membership":
        return None

    gewaehlt = {t for t in (_typ(x) for x in (cfg.get("xrechnung_karteitypen") or [])) if t}
    typ = _typ(inv.get("karteityp"))
    if gewaehlt and typ is not None and typ not in gewaehlt:
        return {"regel": "karteityp", "karteityp": typ,
                "text": f"Karteityp „{typname(typ)}“ des Rechnungsempfängers "
                        "ist nicht für die XRechnung ausgewählt"}

    grenze = _betrag(cfg.get("xrechnung_mindestbetrag"))
    if grenze is not None and grenze > 0 and str(header.get("invoicetypecode") or "") == "380":
        brutto = _betrag((inv.get("totals") or {}).get("invoicegross"))
        # Nur positive Betraege: 0,00 kann eine voll angezahlte Schlussrechnung
        # sein, ein Minus ist eine Gutschrift.
        if brutto is not None and Decimal(0) < brutto < grenze:
            return {"regel": "mindestbetrag", "betrag": f"{brutto:.2f}", "grenze": f"{grenze:.2f}",
                    "text": f"Bruttobetrag {_de(brutto)} liegt unter dem Mindestbetrag {_de(grenze)}"}
    return None


def karteitypen_auswahl() -> list[tuple[str, str]]:
    """Karteitypen, die es in dieser Suite8 gibt: [(Wert, Beschriftung)] mit
    der Bezeichnung aus XCCA und der Anzahl der Karteien. Nur SELECT. Ohne
    Datenbank eine leere Liste."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(_AUSWAHL_SQL)
            rows = cur.fetchall()
    except Exception as e:
        logger.warning("Karteitypen nicht lesbar: %s", e)
        return []
    name: dict[str, str] = {}
    anzahl: dict[str, int] = {}
    for kat, bezeichnung, _inaktiv, n in rows:      # aktive zuerst (Sortierung)
        typ = _typ(kat)
        if typ is None:
            continue
        if typ not in name and str(bezeichnung or "").strip():
            name[typ] = str(bezeichnung).strip()
        anzahl[typ] = anzahl.get(typ, 0) + int(n or 0)
    out = []
    for typ in sorted(anzahl, key=int):
        n = f"{anzahl[typ]:,}".replace(",", ".")
        out.append((typ, f"{name.get(typ) or typname(typ)} ({n} Karteien)"))
    return out
