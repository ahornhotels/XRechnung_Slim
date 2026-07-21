"""Tests fuer die CreditNote-XSD-Konformitaet (UBL-CreditNote-2.1).

Regressionsschutz fuer den Deployment-Blocker cvc-complex-type.2.4.a:
Das UBL-CreditNote-Schema kennt KEIN cbc:DueDate (anders als Invoice).
Wird bei einer Gutschrift header.duedate gesetzt (aus dem SQL via
UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE oder aus _ensure_duedate bei
payableamount>0), darf das CreditNote-XML trotzdem kein DueDate enthalten.

Die interne validate_xsd() sucht die XSD an einem anderen Pfad als sie im
Repo liegt (dort no-op); dieser Test validiert daher direkt gegen die real
vorhandene Schema-Datei.
"""
from pathlib import Path

import pytest
from lxml import etree

from modules import xml_builder

_XSD_DIR = (Path(__file__).resolve().parent.parent
            / "validation" / "xrechnung-3.0.2" / "resources"
            / "ubl" / "2.1" / "xsd" / "maindoc")
_CN_XSD = _XSD_DIR / "UBL-CreditNote-2.1.xsd"
_INV_XSD = _XSD_DIR / "UBL-Invoice-2.1.xsd"


def _assert_xsd_valid(xml_bytes: bytes, xsd_path: Path):
    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    doc = etree.fromstring(xml_bytes)
    if not schema.validate(doc):
        errors = "\n".join(str(e) for e in schema.error_log)
        pytest.fail(f"XSD-Validierung fehlgeschlagen:\n{errors}")


def _base_invoice(role, **header_over):
    """Minimal-vollstaendige, XSD-taugliche Rechnung. role=3 -> CreditNote."""
    header = {
        "id": "GS-2026-0001",
        "issuedate": "2026-07-15",
        "invoicetypecode": "381" if role == 3 else "380",
        "zinvrole": role,
        "documentcurrencycode": "EUR",
        "buyerreference": "Leitweg-1",
        "billingreferenceid": "RG-2026-0815",
        "billingreferenceissuedate": "2026-06-30",
        "suppliername": "Testhotel GmbH",
        "supplierstreetname": "Hauptstr. 1",
        "suppliercityname": "Musterstadt",
        "supplierpostalzone": "12345",
        "supplieridentificationcode": "DE",
        "suppliercompanyid": "DE123456789",
        "supplierregistrationname": "Testhotel GmbH",
        "suppliercontactname": "Buchhaltung",
        "customername": "Kunde AG",
        "customerstreetname": "Kundenweg 2",
        "customercityname": "Kundenstadt",
        "customerpostalzone": "54321",
        "customeridentificationcode": "DE",
        "customerregistrationname": "Kunde AG",
        "payeefinancialaccountid": "DE00123456780000000000",
        "payeefinancialaccountname": "Testhotel GmbH",
    }
    header.update(header_over)
    return {
        "zinv_id": 1,
        "header": header,
        "lines": [{
            "invoicedquantity": "1",
            "lineextensionamount": "-100.00",
            "lineextensionamountnet": "-100.00",
            "priceamount": "-100.00",
            "itemname": "Uebernachtung (Storno)",
            "classifiedtaxcategoryid": "S",
            "classifiedtaxcategorypercent": "19.00",
        }],
        "tax_breakdown": [{
            "taxableamount": "-100.00",
            "taxamount": "-19.00",
            "taxcategoryid": "S",
            "taxcategorypercent": "19.00",
        }],
        "totals": {
            "invoicenet": -100.00,
            "invoicegross": -119.00,
            "invoicetaxtotal": -19.00,
            "taxexclusiveamount": -100.00,
            "spay_cl": 0.0,
        },
    }


# ─────────────── CreditNote: kein DueDate, XSD-valide ───────────────

def test_creditnote_mit_header_duedate_hat_kein_duedate_element():
    """duedate aus dem SQL (UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE) darf im
    CreditNote-XML nicht als cbc:DueDate landen (nicht im UBL-CN-Schema)."""
    inv = _base_invoice(role=3, duedate="2026-07-29")
    xml = xml_builder.render(inv)
    assert b"<cbc:DueDate" not in xml
    _assert_xsd_valid(xml, _CN_XSD)


def test_creditnote_ohne_duedate_bei_payable_positiv_bleibt_valide():
    """_ensure_duedate darf einer CreditNote kein duedate anhaengen, das das
    Template sonst als (schemawidriges) cbc:DueDate rendern wuerde."""
    inv = _base_invoice(role=3, payableamount="119.00")
    inv["header"].pop("duedate", None)
    xml = xml_builder.render(inv)
    assert b"<cbc:DueDate" not in xml
    _assert_xsd_valid(xml, _CN_XSD)


# ─────────────── Regression: Invoice behaelt DueDate ───────────────

def test_invoice_behaelt_duedate_element():
    """Der Fix darf DueDate nicht global entfernen: die regulaere Rechnung
    (Invoice-Schema erlaubt BT-9) rendert es weiterhin."""
    inv = _base_invoice(role=0, duedate="2026-07-29")
    # positive Betraege fuer eine echte Invoice
    inv["lines"][0].update(lineextensionamount="100.00",
                           lineextensionamountnet="100.00",
                           priceamount="100.00")
    inv["tax_breakdown"][0].update(taxableamount="100.00", taxamount="19.00")
    inv["totals"].update(invoicenet=100.0, invoicegross=119.0,
                         invoicetaxtotal=19.0, taxexclusiveamount=100.0)
    xml = xml_builder.render(inv)
    assert b"<cbc:DueDate>2026-07-29</cbc:DueDate>" in xml
    _assert_xsd_valid(xml, _INV_XSD)
