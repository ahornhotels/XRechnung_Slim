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


def apply_customer_address(header: dict) -> None:
    """Verteilt Strasse 1/2/3 auf StreetName, AdditionalStreetName, AddressLine.

    Quelle ist die Rechnungsadresse (ZINV_XADR_ID); hat sie keine Strasse,
    die Primaeradresse. Liefert das SQL die Spalten nicht (alter
    Override), bleibt der Kopf unveraendert.
    """
    if not any(k in header for k in _ADR_KEYS + _PRIM_KEYS):
        return
    # Strassenzeilen nie zwischen den Adressen mischen: entweder alle aus der
    # Rechnungsadresse oder - wenn diese keine Strasse hat - alle aus der
    # Primaeradresse. Letzteres entspricht dem bisherigen nvl() im SQL; viele
    # Rechnungsadressen haben keine Strasse, sie duerfen nicht blockiert werden.
    lines = (street_lines(*(header.get(k) for k in _ADR_KEYS))
             or street_lines(*(header.get(k) for k in _PRIM_KEYS)))
    if not lines:
        return
    lines += [None, None]
    header["customerstreetname"] = lines[0]
    header["customeradditionalstreetname"] = lines[1]
    header["customeraddressline"] = lines[2]


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
