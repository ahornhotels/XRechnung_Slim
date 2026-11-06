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
FRAG = ("when z.zpos_taxlink_id is not null and not exists (select 1 from zpos Z3 where "
        "Z3.zpos_taxlink_id=z.zpos_taxlink_id and Z3.zpos_cdt=2) then 0")
PAIDOUT_WHERE = "(z.zpos_cdt=1 or (z.zpos_cdt=5 and z.zpos_paidout=1))"
SIGN = "round(z.zpos_grossunitprice*z.zpos_quantity*decode(z.zpos_cdt,5,-1,1),2)"


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
    z_count = sum(1 for s in doc.findall("cac:TaxTotal/cac:TaxSubtotal", NS)
                  if s.findtext("cac:TaxCategory/cbc:ID", namespaces=NS) == "Z")
    assert z_count == 1
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


def _flat(name):
    return (SQL_DIR / f"invoice_{name}.sql").read_text(encoding="utf-8").replace(" ", "").replace(chr(10), "").lower()


def test_ohne_taxlink_bleibt_satz_unbestimmt():
    """TAXLINK NULL: Satz nicht ermittelbar -> weiter Fehler, nicht still 0 %."""
    for name in ("lines", "tax", "totals"):
        assert "z.zpos_taxlink_idisnotnullandnotexists" in _flat(name), name


def test_paidout_ist_position_in_allen_drei_sql():
    """Nutzerentscheidung (a) wie OPERA: Paid-Out (CDT 5, PAIDOUT 1) ist eine
    Auslage-Position mit Z 0 %, Betrag mit umgekehrtem Vorzeichen."""
    for name in ("lines", "tax", "totals"):
        sql = _flat(name)
        assert PAIDOUT_WHERE.replace(" ", "").lower() in sql, name
        assert SIGN.replace(" ", "").lower() in sql, name
        assert "when z.zpos_cdt=5 then 0" in (SQL_DIR / f"invoice_{name}.sql").read_text(encoding="utf-8").lower(), name


def test_override_marker_fuer_neue_satzlogik():
    from modules.invoice_fetcher import _EXPECTED_OVERRIDE_MARKERS
    for name in ("invoice_lines.sql", "invoice_tax.sql", "invoice_totals.sql"):
        assert "Z3.zpos_cdt=2" in _EXPECTED_OVERRIDE_MARKERS[name], name


def test_lines_sql_meldet_fehlende_steuerbuchung():
    assert "taxlinecount" in _flat("lines")


def test_position_ohne_steuerbuchung_gibt_warnung_kein_fehler():
    inv = _auslagen_rechnung()
    for ln in inv["lines"]:
        ln["taxlinecount"] = 0 if ln["classifiedtaxcategoryid"] == "Z" else 1
    issues = invoice_validator.validate(inv)
    warn = [i for i in issues if i["field"] == "lines.tax_missing"]
    assert len(warn) == 1 and warn[0]["severity"] == "warning"
    assert "Auslagen Gastronomie" in warn[0]["message"]
    assert not [i for i in issues if i["field"].endswith("tax_percent")]
