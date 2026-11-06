"""Tests: Leistungszeilen ohne Steuerzeile (CDT 2) als Z 0 %.

Live-Befund (nur SELECT): Auslagen wie "Auslagen Gastronomie" oder
"Durchlaufender Posten" haben keine CDT-2-Partnerzeile. Bisher ergab das
ClassifiedTaxCategoryPercent = NULL, damit auch Netto NULL, und der Validator
blockte die Rechnung ("USt-Satz nicht ermittelbar").
"""
from pathlib import Path

from lxml import etree

from modules import invoice_validator, xml_builder
from tests_slim.test_creditnote_xsd import _INV_XSD, _assert_xsd_valid
from tests_slim.test_deposit_allowances import _invoice, _line

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}
FRAG = ("(select 0 from dual where not exists (select 1 from zpos Z3 where "
        "Z3.zpos_taxlink_id=z.zpos_taxlink_id and Z3.zpos_cdt=2))")


def _z(name, amount):
    ln = _line(name, amount, amount, 0)
    ln["classifiedtaxcategoryid"] = "Z"
    ln["classifiedtaxcategorypercent"] = "0"
    return ln


def _auslagen_rechnung():
    """19 % + 7 % Leistungen und fuenf Auslagen ohne Steuer (zusammen 15,00)."""
    lines = [_line("Getraenke", 119.00, 100.00, 19), _line("Fruehstueck", 53.50, 50.00, 7)]
    lines += [_z("Auslagen Gastronomie", a) for a in (3.00, 4.00, 5.00, 1.00, 2.00)]
    inv = _invoice(lines, gross=187.50, net=165.00, tax=22.50)
    inv["tax_breakdown"] = [
        {"taxcategoryid": "S", "taxcategorypercent": "19.00", "taxableamount": "100.00", "taxamount": "19.00"},
        {"taxcategoryid": "S", "taxcategorypercent": "7.00", "taxableamount": "50.00", "taxamount": "3.50"},
    ]
    return inv


def test_satz_ohne_steuerzeile_ist_null_prozent_in_allen_drei_sql():
    norm = FRAG.replace(" ", "").lower()
    for name in ("lines", "tax", "totals"):
        sql = (SQL_DIR / f"invoice_{name}.sql").read_text(encoding="utf-8")
        assert norm in sql.replace(" ", "").replace("\n", "").lower(), name


def test_z_auslage_wird_nicht_geblockt():
    issues = invoice_validator.validate(_auslagen_rechnung())
    assert not [i for i in issues if i["field"].endswith("tax_percent")]


def test_xml_z_auslage_neben_19_und_7():
    xml = xml_builder.render(_auslagen_rechnung())
    doc = etree.fromstring(xml)
    groups = {(s.findtext("cac:TaxCategory/cbc:ID", namespaces=NS),
               s.findtext("cac:TaxCategory/cbc:Percent", namespaces=NS)):
              (s.findtext("cbc:TaxableAmount", namespaces=NS), s.findtext("cbc:TaxAmount", namespaces=NS))
              for s in doc.findall("cac:TaxTotal/cac:TaxSubtotal", NS)}
    assert groups[("Z", "0.00")] == ("15.00", "0.00")
    assert len([k for k in groups if k[0] == "Z"]) == 1
    _assert_xsd_valid(xml, _INV_XSD)


def test_negative_z_auslage_wird_abschlag_z():
    inv = _auslagen_rechnung()
    inv["lines"].append(_z("Auslagen Korrektur", -2.00))
    inv["totals"].update(invoicegross=185.50, invoicenet=163.00)
    doc = etree.fromstring(xml_builder.render(inv))
    acs = doc.findall("cac:AllowanceCharge", NS)
    assert [(a.findtext("cac:TaxCategory/cbc:ID", namespaces=NS),
             a.findtext("cac:TaxCategory/cbc:Percent", namespaces=NS),
             a.findtext("cbc:Amount", namespaces=NS)) for a in acs] == [("Z", "0.00", "2.00")]
