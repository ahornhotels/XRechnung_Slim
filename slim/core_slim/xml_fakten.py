"""
slim/core_slim/xml_fakten.py
----------------------------
Kerndaten einer archivierten XRechnung (UBL Invoice/CreditNote) fuer die
Archivliste: Nummer, Rechnungsdatum, Art, Zahlbetrag, Waehrung, Kaeufer.

Gelesen wird die archivierte Datei selbst, nicht Suite8 - das Archiv zeigt,
was tatsaechlich gesendet wurde. Unlesbare oder fremde Dokumente liefern {}.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

CBC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
CAC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"
_ROOTS = {
    "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice": "Rechnung",
    "{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote": "Gutschrift",
}


def parse(xml_bytes: bytes):
    """(root, art) oder (None, None). ElementTree loest keine externen Entitaeten auf;
    eine DOCTYPE-Deklaration (einziger Ort fuer Entitaeten) wird gar nicht erst
    geparst - eine XRechnung hat nie eine."""
    if b"<!DOCTYPE" in xml_bytes.upper():
        return None, None
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None, None
    art = _ROOTS.get(root.tag)
    return (root, art) if art else (None, None)


def text(el, path: str):
    if el is None:
        return None
    found = el.find(path)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def lies(xml_bytes: bytes) -> dict:
    root, art = parse(xml_bytes)
    if root is None:
        return {}
    party = root.find(f"{CAC}AccountingCustomerParty/{CAC}Party")
    payable = root.find(f"{CAC}LegalMonetaryTotal/{CBC}PayableAmount")
    return {
        "rechnung": text(root, f"{CBC}ID"),
        "rechnungsdatum": text(root, f"{CBC}IssueDate"),
        "art": art,
        "betrag": payable.text.strip() if payable is not None and payable.text else None,
        "waehrung": text(root, f"{CBC}DocumentCurrencyCode")
        or (payable.get("currencyID") if payable is not None else None),
        "kaeufer": text(party, f"{CAC}PartyLegalEntity/{CBC}RegistrationName")
        or text(party, f"{CAC}PartyName/{CBC}Name"),
    }
