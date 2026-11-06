"""
modules/invoice_enrich.py
-------------------------
Reine Aufbereitung der Suite8-Rohdaten nach dem Fetch (ohne DB-Zugriff).
Laeuft in invoice_fetcher.fetch_invoice, VOR dem Validator.

- Kaeuferadresse aus Strasse 1/2/3 (BT-50, BT-51, BT-163)
- Gastzeile (BT-22) und Lieferempfaenger (BT-70) bei genau einem Gast
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_ADR_KEYS = ("customeradrstreet1", "customeradrstreet2", "customeradrstreet3")
_PRIM_KEYS = ("customerprimstreet1", "customerprimstreet2", "customerprimstreet3")


def street_lines(*raw: Optional[str]) -> list[str]:
    """Nicht leere Strassenzeilen in Reihenfolge, getrimmt."""
    return [str(v).strip() for v in raw if v is not None and str(v).strip()]


_CITY_KEYS = tuple(f"{p}{f}" for p in ("customeradr", "customerprim")
                   for f in ("city", "zip", "country"))
_warned_old_address_sql = False


def _clean(v) -> Optional[str]:
    return None if v is None or not str(v).strip() else str(v).strip()


def _set_street_lines(header: dict, lines: list) -> None:
    lines = list(lines) + [None, None, None]
    header["customerstreetname"] = lines[0]
    header["customeradditionalstreetname"] = lines[1]
    header["customeraddressline"] = lines[2]


def _apply_whole_address(header: dict) -> None:
    """Adresse nie splitten: Strasse, Ort, PLZ und Land aus GENAU einer
    XADR-Zeile. Gewaehlt wird die vollstaendigere Adresse (alles da > Strasse
    da > mehr Felder), bei Gleichstand die Rechnungsadresse. Fehlende Felder
    der gewaehlten Adresse werden NICHT aus der anderen ergaenzt."""
    candidates = []
    for src, keys, is_billing in (("customeradr", _ADR_KEYS, 1), ("customerprim", _PRIM_KEYS, 0)):
        if is_billing and _blank(header.get("customeradrid")):
            continue
        lines = street_lines(*(header.get(k) for k in keys))
        fields = [_clean(header.get(f"{src}{f}")) for f in ("city", "zip", "country")]
        n = sum(1 for v in fields if v)
        score = (bool(lines) and n == 3, bool(lines), n, is_billing)
        candidates.append((score, lines, fields))
    _, lines, (city, zip_, country) = max(candidates, key=lambda c: c[0])
    _set_street_lines(header, lines)
    header["customercityname"] = city
    header["customerpostalzone"] = zip_
    header["customeridentificationcode"] = country


def apply_customer_address(header: dict) -> None:
    """Verteilt Strasse 1/2/3 auf StreetName, AdditionalStreetName, AddressLine.

    Quelle ist die Rechnungsadresse (ZINV_XADR_ID); hat sie keine Strasse,
    die Primaeradresse - immer die ganze Adresse (_apply_whole_address). Liefert das SQL die Spalten nicht (alter
    Override), bleibt der Kopf unveraendert.
    """
    if not any(k in header for k in _ADR_KEYS + _PRIM_KEYS):
        return
    if all(k in header for k in _CITY_KEYS):
        _apply_whole_address(header)
        return
    global _warned_old_address_sql
    if not _warned_old_address_sql:
        _warned_old_address_sql = True
        logger.warning("invoice_header.sql (SQL-Override?) liefert Ort/PLZ/Land nicht je "
                       "Adresse - Strasse und Ort koennen aus verschiedenen Adressen stammen. "
                       "Override aus sql/invoice_header.sql neu ableiten.")
    # Strassenzeilen nie zwischen den Adressen mischen: entweder alle aus der
    # Rechnungsadresse oder - wenn diese keine Strasse hat - alle aus der
    # Primaeradresse. Letzteres entspricht dem bisherigen nvl() im SQL; viele
    # Rechnungsadressen haben keine Strasse, sie duerfen nicht blockiert werden.
    lines = (street_lines(*(header.get(k) for k in _ADR_KEYS))
             or street_lines(*(header.get(k) for k in _PRIM_KEYS)))
    if not lines:
        return
    _set_street_lines(header, lines)


# --- Gast (BT-22 Gastzeile, BT-70 Lieferempfaenger) -------------------------

GASTZEILE_STANDARD = "Gast: {gast}, Zimmer {zimmer}, {anreise} bis {abreise}"
_HINWEIS_TRENNER = " · "


def de_date(iso) -> str:
    """'2026-02-06' -> '06.02.2026' (unveraendert, wenn nicht parsebar)."""
    s = str(iso or "")[:10]
    parts = s.split("-")
    return f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else s


def _blank(v) -> bool:
    return v is None or not str(v).strip()


def guests(lines: list[dict]) -> list[dict]:
    """Je eindeutigem (Herkunftsreservierung, Gastprofil) ein Gast-Dict
    {gast, zimmer, anreise, abreise}. Es zaehlen nur Positionen mit
    Herkunftsreservierung, ohne Anzahlungszeilen; Reihenfolge = erstes
    Auftreten, Zimmer = das der ersten Position dieses Gastes."""
    from modules.invoice_fetcher import is_deposit_line
    seen: dict[tuple, dict] = {}
    for ln in lines or []:
        if is_deposit_line(ln) or _blank(ln.get("originyresid")):
            continue
        key = (ln.get("originyresid"), ln.get("originxcmsid"))
        if key in seen:
            continue
        seen[key] = {
            "gast": ln.get("originguestname"),
            "zimmer": ln.get("originroom"),
            "anreise": de_date(ln.get("originarrival")) if ln.get("originarrival") else None,
            "abreise": de_date(ln.get("origindeparture")) if ln.get("origindeparture") else None,
        }
    return list(seen.values())


def guest_line(template: str, guest: dict) -> Optional[str]:
    """Vorlage an ', ' in Segmente teilen; ein Segment entfaellt, wenn einer
    seiner Platzhalter leer ist. Ohne Gast oder ohne Vorlage: None."""
    import string
    if _blank(template) or _blank(guest.get("gast")):
        return None
    values = {k: ("" if v is None else str(v).strip()) for k, v in guest.items()}
    out = []
    try:
        for seg in template.split(", "):
            names = [f for _, f, _, _ in string.Formatter().parse(seg) if f is not None]
            if any(not values.get(n) for n in names):
                continue
            out.append(seg.format(**{n: values[n] for n in names}))
    except (ValueError, IndexError, KeyError) as e:
        # Tippfehler in der Vorlage darf keine Rechnung blockieren.
        logger.warning("Gastzeilen-Vorlage %r ungueltig (%s) - keine Gastzeile", template, e)
        return None
    return ", ".join(out) or None


def apply_guest_info(invoice: dict, template: str) -> None:
    """Genau ein Gast: Gastzeile an BT-22 (header.note) anhaengen und den Namen
    als BT-70 (header.deliverypartyname) setzen. Sonst kein Kopf-Gast."""
    header = invoice.setdefault("header", {})
    header["deliverypartyname"] = None
    gs = guests(invoice.get("lines") or [])
    if len(gs) != 1 or _blank(gs[0].get("gast")):
        return
    header["deliverypartyname"] = str(gs[0]["gast"]).strip()
    line = guest_line(template, gs[0])
    if line:
        note = header.get("note")
        header["note"] = f"{note}{_HINWEIS_TRENNER}{line}" if not _blank(note) else line
