"""
slim/core_slim/xml_ansicht.py
-----------------------------
Lesbare Darstellung einer archivierten XRechnung (UBL Invoice/CreditNote):
Kopf, Verkaeufer, Kaeufer, Positionen, Ab-/Zuschlaege, Steuern, Summen,
Bemerkungen, Bezuege, Zahlungsangaben - jede Angabe, die die Vorlagen schreiben.

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
        "email": text(party, f"{CBC}EndpointID"),
        "zusatz": text(adr, f"{CBC}AdditionalStreetName"),
        "adresszeile": text(adr, f"{CAC}AddressLine/{CBC}Line"),
        "land": text(adr, f"{CAC}Country/{CBC}IdentificationCode"),
        "kontakt": _kontakt(party.find(f"{CAC}Contact")),
    }


def _kontakt(c) -> Optional[dict]:
    if c is None:
        return None
    return {"name": text(c, f"{CBC}Name"), "telefon": text(c, f"{CBC}Telephone"),
            "email": text(c, f"{CBC}ElectronicMail")}


def _kopf(root) -> dict:
    """Kopfangaben neben Nummer und Datum: Art, Faelligkeit, Zeitraum, Bezuege,
    Leistungsempfaenger, Zahlungsangaben - alles, was in der Datei steht."""
    pm = root.find(f"{CAC}PaymentMeans")
    konto = pm.find(f"{CAC}PayeeFinancialAccount") if pm is not None else None
    return {
        "typ": text(root, f"{CBC}InvoiceTypeCode") or text(root, f"{CBC}CreditNoteTypeCode"),
        "faellig": text(root, f"{CBC}DueDate"),
        "von": text(root, f"{CAC}InvoicePeriod/{CBC}StartDate"),
        "bis": text(root, f"{CAC}InvoicePeriod/{CBC}EndDate"),
        "bestellnummer": text(root, f"{CAC}OrderReference/{CBC}ID"),
        "bezuege": [{"nr": text(r, f"{CBC}ID"), "datum": text(r, f"{CBC}IssueDate")}
                    for r in root.findall(f"{CAC}BillingReference/{CAC}InvoiceDocumentReference")],
        "leistungsempfaenger": text(root, f"{CAC}Delivery/{CAC}DeliveryParty/{CAC}PartyName/{CBC}Name"),
        "zahlungsbedingungen": text(root, f"{CAC}PaymentTerms/{CBC}Note"),
        "zahlung": None if pm is None else {
            "code": text(pm, f"{CBC}PaymentMeansCode"),
            "konto": text(konto, f"{CBC}ID"),
            "inhaber": text(konto, f"{CBC}Name"),
            "bic": text(konto, f"{CAC}FinancialInstitutionBranch/{CBC}ID"),
        },
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
            "hinweis": text(ln, f"{CBC}Note"),
            "von": text(ln, f"{CAC}InvoicePeriod/{CBC}StartDate"),
            "bis": text(ln, f"{CAC}InvoicePeriod/{CBC}EndDate"),
        })
    nachlaesse = [{
        "zuschlag": (text(ac, f"{CBC}ChargeIndicator") or "").lower() == "true",
        "grund": text(ac, f"{CBC}AllowanceChargeReason"),
        "betrag": text(ac, f"{CBC}Amount"),
        "kategorie": text(ac, f"{CAC}TaxCategory/{CBC}ID"),
        "prozent": text(ac, f"{CAC}TaxCategory/{CBC}Percent"),
    } for ac in root.findall(f"{CAC}AllowanceCharge")]
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
        "kopf": _kopf(root),
        "nachlaesse": nachlaesse,
        "verkaeufer": _party(root.find(f"{CAC}AccountingSupplierParty/{CAC}Party")),
        "kaeufer": _party(root.find(f"{CAC}AccountingCustomerParty/{CAC}Party")),
        "positionen": positionen,
        "steuern": steuern,
        "summen": {
            "positionen": text(lmt, f"{CBC}LineExtensionAmount"),
            "abschlaege": text(lmt, f"{CBC}AllowanceTotalAmount"),
            "zuschlaege": text(lmt, f"{CBC}ChargeTotalAmount"),
            "netto": text(lmt, f"{CBC}TaxExclusiveAmount"),
            "steuer": text(root, f"{CAC}TaxTotal/{CBC}TaxAmount"),
            "brutto": text(lmt, f"{CBC}TaxInclusiveAmount"),
            "vorauszahlung": text(lmt, f"{CBC}PrepaidAmount"),
            "zahlbetrag": text(lmt, f"{CBC}PayableAmount"),
        },
        "hinweise": [n.text.strip() for n in root.findall(f"{CBC}Note") if n.text and n.text.strip()],
    }
