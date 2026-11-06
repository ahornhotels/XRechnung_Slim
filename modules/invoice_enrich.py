"""
modules/invoice_enrich.py
-------------------------
Reine Aufbereitung der Suite8-Rohdaten nach dem Fetch (ohne DB-Zugriff).
Laeuft in invoice_fetcher.fetch_invoice, VOR dem Validator.

- Kaeuferadresse aus Strasse 1/2/3 (BT-50, BT-51, BT-163)
"""
from typing import Optional

_ADR_KEYS = ("customeradrstreet1", "customeradrstreet2", "customeradrstreet3")
_PRIM_KEYS = ("customerprimstreet1", "customerprimstreet2", "customerprimstreet3")


def street_lines(*raw: Optional[str]) -> list[str]:
    """Nicht leere Strassenzeilen in Reihenfolge, getrimmt."""
    return [str(v).strip() for v in raw if v is not None and str(v).strip()]


def apply_customer_address(header: dict) -> None:
    """Verteilt Strasse 1/2/3 auf StreetName, AdditionalStreetName, AddressLine.

    Quelle ist die Rechnungsadresse (ZINV_XADR_ID), wenn es sie gibt, sonst
    die Primaeradresse. Liefert das SQL die Spalten nicht (alter
    Override), bleibt der Kopf unveraendert.
    """
    if not any(k in header for k in _ADR_KEYS + _PRIM_KEYS):
        return
    if "customeradrid" in header:
        # Eine Quelle je Adresse: existiert die Rechnungsadresse, kommt die
        # Strasse nur aus ihr (sonst Primaer-Strasse mit fremdem Ort/PLZ).
        keys = _ADR_KEYS if header.get("customeradrid") else _PRIM_KEYS
        lines = street_lines(*(header.get(k) for k in keys))
    else:
        lines = (street_lines(*(header.get(k) for k in _ADR_KEYS))
                 or street_lines(*(header.get(k) for k in _PRIM_KEYS)))
    if not lines:
        if header.get("customeradrid"):
            header["customerstreetname"] = None
            header["customeradditionalstreetname"] = None
            header["customeraddressline"] = None
        return
    lines += [None, None]
    header["customerstreetname"] = lines[0]
    header["customeradditionalstreetname"] = lines[1]
    header["customeraddressline"] = lines[2]
