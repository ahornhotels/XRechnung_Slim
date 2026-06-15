"""
modules/invoice_validator.py
----------------------------
Prueft Suite8-Rohdaten gegen XRechnung-Pflichtfelder.
Gibt Liste von Issues zurueck: [{field, severity, message}, ...]

Severity:
  'error'   - blockiert XRechnung-Versand (in Queue)
  'warning' - sollte ergaenzt werden, blockiert aber nicht (Versand mit Hinweis)
"""
from typing import Any


REQUIRED_HEADER_FIELDS: dict[str, tuple[str, str]] = {
    "id":                          ("invoice.number",       "Rechnungsnummer fehlt"),
    "issuedate":                   ("invoice.date",         "Rechnungsdatum fehlt"),
    "invoicetypecode":             ("invoice.type",         "InvoiceTypeCode fehlt"),
    # documentcurrencycode: NICHT mehr Pflicht im Validator - der invoice_fetcher
    # fuellt es mit dem Hotel-Default aus config/hotel.json (default 'EUR') wenn
    # Suite8 nichts liefert. Damit es im XML korrekt erscheint.
    "suppliername":                ("supplier.name",        "Hotel-Name fehlt (WUSS.Hotelid)"),
    "supplierstreetname":          ("supplier.street",      "Hotel-Strasse fehlt (WUSS.HotelAddress)"),
    "suppliercityname":            ("supplier.city",        "Hotel-Ort fehlt (WUSS.Hotelcity)"),
    "supplierpostalzone":          ("supplier.zip",         "Hotel-PLZ fehlt (WUSS.Hotelzipcode)"),
    "supplieridentificationcode":  ("supplier.country",     "Hotel-Land fehlt (WUSS.Hotelcountry -> XCOU.XCOU_ISO2)"),
    "suppliercompanyid":           ("supplier.tax_id",      "Hotel-UStID fehlt (WUSS.HotelTaxNumber)"),
    "payeefinancialaccountid":     ("supplier.iban",        "Hotel-IBAN fehlt (WUSS.HotelbankIBAN)"),
    "customername":                ("customer.name",        "Kundenname fehlt (XCMS.XCMS_NAME1)"),
    "customerstreetname":          ("customer.street",      "Kunden-Strasse fehlt (XADR.XADR_STREET1)"),
    "customercityname":            ("customer.city",        "Kunden-Ort fehlt (XADR.XADR_CITY)"),
    "customerpostalzone":          ("customer.zip",         "Kunden-PLZ fehlt (XADR.XADR_ZIP)"),
    "customeridentificationcode":  ("customer.country",     "Kunden-Land fehlt (XADR.XADR_XCOU_ID -> XCOU.XCOU_ISO2)"),
    "customerendpointid":          ("customer.email",       "Kunden-E-Mail fehlt - benoetigt fuer Versand (XCOM mit XCMT_TYPE=1, oder XCMS.XCMS_EMAIL). Im Queue-Eintrag kann ein recipient_email-Override gesetzt werden."),
    "buyerreference":              ("buyer.reference",      "Kaeuferreferenz fehlt (XMNR mit XMTY_SHORTDESC='DXR')"),
}


def _is_empty(value: Any) -> bool:
    """True wenn value None, leerer String oder nur Whitespace."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def validate(invoice: dict) -> list[dict]:
    """Validiert ein Invoice-Dict gegen XRechnung-Pflichtfelder.

    Args:
        invoice: Dict mit Keys 'header', 'lines', 'tax_breakdown', 'totals'

    Returns:
        Liste von Issues. Leere Liste = alles ok.
    """
    issues: list[dict] = []
    header = invoice.get("header") or {}

    for key, (field, message) in REQUIRED_HEADER_FIELDS.items():
        if _is_empty(header.get(key)):
            issues.append({"field": field, "severity": "error", "message": message})

    lines = invoice.get("lines") or []
    if not lines:
        issues.append({
            "field": "lines",
            "severity": "error",
            "message": "Keine Positionen (ZPIL/ZPI2 leer)"
        })

    for idx, line in enumerate(lines):
        if line.get("classifiedtaxcategorypercent") is None:
            issues.append({
                "field": f"lines[{idx}].tax_percent",
                "severity": "error",
                "message": f"Position {idx+1} ({line.get('itemname', '?')}): USt-Satz nicht ermittelbar"
            })

    totals = invoice.get("totals") or {}
    if totals.get("invoicegross") is None:
        issues.append({
            "field": "totals.gross",
            "severity": "error",
            "message": "Brutto-Betrag nicht berechnet"
        })

    # BR-pre-check: Rechnungen mit Netto = 0 sind keine versendbare XRechnung
    # (z.B. Pfand-Buchung + Pfand-Rueckgabe in einer Rechnung).
    # Wir lehnen sie hier ab, BEVOR KoSIT mit unklarem BR-S-01-Fehler anschlaegt.
    try:
        gross_val = float(totals.get("invoicegross") or 0)
        net_val   = float(totals.get("invoicenet")   or 0)
    except (TypeError, ValueError):
        gross_val, net_val = 0.0, 0.0
    if abs(gross_val) < 0.005 and abs(net_val) < 0.005:
        issues.append({
            "field":    "totals.net",
            "severity": "error",
            "message":  ("Nicht versendbar: Rechnungs-Netto und -Brutto sind 0 EUR "
                         "(intern aufgehobene Pfand-/Storno-Buchung). "
                         "XRechnung ist nur fuer tatsaechlich abzurechnende Betraege "
                         "sinnvoll - bitte in Suite8 stornieren oder ausserhalb "
                         "XRechnung abwickeln."),
        })

    # CreditNote-Pflichtfeld: BillingReference auf Original-Rechnung
    if (header.get("invoicetypecode") or "") == "381":
        if not (header.get("billingreferenceid") or "").strip():
            issues.append({
                "field":    "billing_reference",
                "severity": "error",
                "message":  (
                    "Gutschrift braucht Bezug zur Original-Rechnung "
                    "(BG-3 InvoiceDocumentReference). In Suite8 die "
                    "Storno-Rechnung mit Bezug zur Original anlegen "
                    "(ZINV_VOID_ZINV_ID setzen)."
                ),
            })

    return issues
