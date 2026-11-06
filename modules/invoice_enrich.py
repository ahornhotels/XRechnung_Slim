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


# --- Auslagen ohne Steuerbuchung (Freigabeliste) ----------------------------

AUSLAGEN_ARTIKEL_STANDARD = ["AUS", "DUR"]


def apply_auslagen_freigabe(lines: list[dict], allowed: list[str]) -> None:
    """Leistungen ohne Steuerbuchung in Suite8 liefert das SQL mit 0 %. Das ist
    nur fuer echte Auslagen richtig. Ist der Artikel (ZDCO-Kurzname) nicht
    freigegeben, wird der Satz wieder unbestimmt und die Rechnung blockiert -
    eine steuerpflichtige Leistung ohne Steuerbuchung ist ein Suite8-Fehler.
    Paid-Out (CDT 5) ist immer eine Auslage."""
    from decimal import Decimal, InvalidOperation
    ok = {str(a).strip().upper() for a in (allowed or []) if str(a).strip()}
    candidates: dict[str, list[dict]] = {}
    for ln in lines or []:
        try:
            no_tax = int(ln.get("taxlinecount")) == 0
            paidout = int(ln.get("ispaidout") or 0) == 1
        except (TypeError, ValueError):
            continue
        if not no_tax or paidout or ln.get("classifiedtaxcategorypercent") is None:
            continue
        code = str(ln.get("itemshortdesc") or "").strip().upper()
        if code not in ok:
            candidates.setdefault(code, []).append(ln)
    for group in candidates.values():
        # Fehlbuchung samt Storno (+x / -x) laesst nichts Steuerpflichtiges uebrig.
        try:
            total = sum(Decimal(str(ln.get("lineextensionamount") or 0)) for ln in group)
        except InvalidOperation:
            total = Decimal(1)
        if total == 0:
            continue
        for ln in group:
            ln["classifiedtaxcategorypercent"] = None
            ln["taxmissing"] = True


# --- Positionen zusammenfassen, Gruppenrechnung (BT-127, BT-134/135) --------


def _d(v):
    from decimal import Decimal, InvalidOperation
    if v is None or str(v).strip() == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _qty_text(q) -> str:
    s = format(q.normalize(), "f")
    return s if s not in ("-0", "") else "0"


def guest_label(ln: dict) -> Optional[str]:
    """'Zi. 101 · Erika Muster' (ohne Zimmer nur der Name; ohne Herkunft/Gast None)."""
    if _blank(ln.get("originyresid")) or _blank(ln.get("originguestname")):
        return None
    name = str(ln["originguestname"]).strip()
    room = None if _blank(ln.get("originroom")) else str(ln["originroom"]).strip()
    return f"Zi. {room}{_HINWEIS_TRENNER}{name}" if room else name


def _room_sort(room) -> tuple:
    if _blank(room):
        return (2, 0, "")
    r = str(room).strip()
    return (0, int(r), r) if r.isdigit() else (1, 0, r)


def _build_position(members: list[dict], multi: bool) -> dict:
    from decimal import Decimal
    cent, p4 = Decimal("0.01"), Decimal("0.0001")
    pos = dict(members[0])
    nets = [_d(m.get("lineextensionamountnet")) or Decimal(0) for m in members]
    grosses = [_d(m.get("lineextensionamount")) or Decimal(0) for m in members]
    net, gross = sum(nets), sum(grosses)
    pos["lineextensionamountnet"] = str(net.quantize(cent))
    pos["lineextensionamount"] = str(gross.quantize(cent))
    pct = _d(pos.get("classifiedtaxcategorypercent"))
    if pct is not None:
        pos["vatparts"] = str(sum((n * pct / 100).quantize(cent) for n in nets).quantize(cent))
    qtys = [_d(m.get("quantity")) for m in members]
    qty = sum(qtys) if all(q is not None for q in qtys) else None
    price = None
    if qty is not None and qty != 0 and (qty > 0) == (net >= 0):
        price = (net / qty).quantize(p4)
        if (qty * price).quantize(cent) != net.quantize(cent):
            price = None
    if price is None:
        pos["invoicedquantity"], pos["priceamount"] = "1", str(net.quantize(cent))
    else:
        pos["invoicedquantity"], pos["priceamount"] = _qty_text(qty), str(price)
    days = sorted(str(m["postdate"])[:10] for m in members if not _blank(m.get("postdate")))
    if days:
        pos["periodstart"], pos["periodend"] = days[0], days[-1]
    label = guest_label(pos) if multi else None
    pos["note"] = label
    pos["guestlabel"] = label
    return pos


def group_lines(lines: list[dict], merge: bool) -> list[dict]:
    """Fasst gleiche Buchungen zu einer Position mit echter Menge zusammen.
    Schluessel: Herkunft, Gast, Zimmer, Artikel, Brutto-Einzelpreis, Kategorie,
    Satz und VORZEICHEN (Stornos werden nicht verrechnet). Anzahlungszeilen
    bleiben einzeln. Bei mehreren Gaesten Positionstext 'Zi. 101 · Name' und
    Sortierung nach Zimmer. Ohne die neuen SQL-Spalten: unveraendert."""
    from modules.invoice_fetcher import is_deposit_line
    lines = list(lines or [])
    if not any("grossunitprice" in ln for ln in lines):
        return lines
    multi = len(guests(lines)) > 1
    groups: dict = {}
    deposits = []
    for i, ln in enumerate(lines):
        if is_deposit_line(ln):
            deposits.append(ln)
            continue
        net = _d(ln.get("lineextensionamountnet")) or 0
        unit = _d(ln.get("grossunitprice"))
        key = (ln.get("originyresid"), ln.get("originxcmsid"), ln.get("originroom"),
               ln.get("itemcode"), ln.get("itemname"),
               None if unit is None else abs(unit).quantize(_d("0.0001")),
               ln.get("classifiedtaxcategoryid"), ln.get("classifiedtaxcategorypercent"),
               net < 0) if merge else i
        groups.setdefault(key, []).append(ln)
    out = [_build_position(m, multi) for m in groups.values()]
    if multi:
        out.sort(key=lambda p: (_room_sort(p.get("originroom")),
                                str(p.get("originguestname") or ""),
                                str(p.get("itemname") or ""), str(p.get("periodstart") or "")))
    return out + deposits


def extend_invoice_period(header: dict, lines: list[dict]) -> None:
    """BT-73/74 so erweitern, dass alle Positionszeitraeume hineinpassen
    (PEPPOL-EN16931-R110/R111)."""
    starts = [str(ln["periodstart"]) for ln in lines or [] if not _blank(ln.get("periodstart"))]
    ends = [str(ln["periodend"]) for ln in lines or [] if not _blank(ln.get("periodend"))]
    if not starts or not ends:
        return
    s0, e0 = header.get("startdate"), header.get("enddate")
    header["startdate"] = min([str(s0)[:10]] + starts) if not _blank(s0) else min(starts)
    header["enddate"] = max([str(e0)[:10]] + ends) if not _blank(e0) else max(ends)
