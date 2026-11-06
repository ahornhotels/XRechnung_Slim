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

    Quelle ist die Rechnungsadresse (ZINV_XADR_ID); sind dort alle drei Zeilen
    leer, die Primaeradresse. Liefert das SQL die Spalten nicht (alter
    Override), bleibt der Kopf unveraendert.
    """
    if not any(k in header for k in _ADR_KEYS + _PRIM_KEYS):
        return
    lines = street_lines(*(header.get(k) for k in _ADR_KEYS))
    if not lines:
        lines = street_lines(*(header.get(k) for k in _PRIM_KEYS))
    if not lines:
        return
    lines += [None, None]
    header["customerstreetname"] = lines[0]
    header["customeradditionalstreetname"] = lines[1]
    header["customeraddressline"] = lines[2]
