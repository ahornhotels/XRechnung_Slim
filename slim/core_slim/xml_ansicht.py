"""
slim/core_slim/xml_ansicht.py
-----------------------------
Lesbare Darstellung einer archivierten XRechnung (UBL Invoice/CreditNote):
Kopf, Verkaeufer, Kaeufer, Positionen, Steuern, Summen, Hinweise.

Quelle ist allein die archivierte Datei - so sieht ein Pruefer genau das, was
gesendet wurde.
"""
from __future__ import annotations

from typing import Optional

from slim.core_slim.xml_fakten import CAC, CBC, lies as fakten, parse, text


def _party(party) -> dict:
    if party is None:
        return {}
    adr = party.find(f"{CAC}PostalAddress")
    ort = " ".join(x for x in (text(adr, f"{CBC}PostalZone"), text(adr, f"{CBC}CityName")) if x)
    return {
        "name": text(party, f"{CAC}PartyLegalEntity/{CBC}RegistrationName")
        or text(party, f"{CAC}PartyName/{CBC}Name"),
        "strasse": text(adr, f"{CBC}StreetName"),
        "ort": ort or None,
        "ust_id": text(party, f"{CAC}PartyTaxScheme/{CBC}CompanyID"),
    }


def lies(xml_bytes: bytes) -> Optional[dict]:
    root, art = parse(xml_bytes)
    if root is None:
        return None
    line_tag, qty_tag = (("InvoiceLine", "InvoicedQuantity") if art == "Rechnung"
                         else ("CreditNoteLine", "CreditedQuantity"))
    positionen = []
    for ln in root.findall(f"{CAC}{line_tag}"):
        qty = ln.find(f"{CBC}{qty_tag}")
        positionen.append({
            "nr": text(ln, f"{CBC}ID"),
            "bezeichnung": text(ln, f"{CAC}Item/{CBC}Name"),
            "menge": qty.text.strip() if qty is not None and qty.text else None,
            "einheit": qty.get("unitCode") if qty is not None else None,
            "preis": text(ln, f"{CAC}Price/{CBC}PriceAmount"),
            "netto": text(ln, f"{CBC}LineExtensionAmount"),
            "steuer_prozent": text(ln, f"{CAC}Item/{CAC}ClassifiedTaxCategory/{CBC}Percent"),
        })
    steuern = [{
        "kategorie": text(st, f"{CAC}TaxCategory/{CBC}ID"),
        "prozent": text(st, f"{CAC}TaxCategory/{CBC}Percent"),
        "basis": text(st, f"{CBC}TaxableAmount"),
        "betrag": text(st, f"{CBC}TaxAmount"),
    } for st in root.findall(f"{CAC}TaxTotal/{CAC}TaxSubtotal")]
    lmt = root.find(f"{CAC}LegalMonetaryTotal")
    f = fakten(xml_bytes)
    f["kaeuferreferenz"] = text(root, f"{CBC}BuyerReference")
    return {
        "fakten": f,
        "verkaeufer": _party(root.find(f"{CAC}AccountingSupplierParty/{CAC}Party")),
        "kaeufer": _party(root.find(f"{CAC}AccountingCustomerParty/{CAC}Party")),
        "positionen": positionen,
        "steuern": steuern,
        "summen": {
            "netto": text(lmt, f"{CBC}TaxExclusiveAmount"),
            "steuer": text(root, f"{CAC}TaxTotal/{CBC}TaxAmount"),
            "brutto": text(lmt, f"{CBC}TaxInclusiveAmount"),
            "vorauszahlung": text(lmt, f"{CBC}PrepaidAmount"),
            "zahlbetrag": text(lmt, f"{CBC}PayableAmount"),
        },
        "hinweise": [n.text.strip() for n in root.findall(f"{CBC}Note") if n.text and n.text.strip()],
    }
