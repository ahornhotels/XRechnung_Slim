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
FRAG = "when z.zpos_taxlink_id is not null then 0"
PAIDOUT_WHERE = "(z.zpos_cdt=1 or (z.zpos_cdt=5 and z.zpos_paidout=1"
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
        assert "whenz.zpos_taxlink_idisnotnullthen0" in _flat(name), name


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
        assert "decode(z.zpos_cdt,5,-1,1)" in _EXPECTED_OVERRIDE_MARKERS[name], name


def test_lines_sql_liefert_steuerzeilen_und_artikelkurzname():
    sql = _flat("lines")
    assert "taxlinecount" in sql and "itemshortdesc" in sql


def _ohne_steuer(shortdesc, name="Getraenke Spaet"):
    ln = _z(name, 9.80)
    ln.update(taxlinecount=0, itemshortdesc=shortdesc, ispaidout=0)
    return ln


def test_freigegebene_auslage_bleibt_null_prozent():
    from modules import invoice_enrich as ie
    lines = [_ohne_steuer("AUS", "Auslagen Gastronomie"), _ohne_steuer("dur", "Kurtaxe alt")]
    ie.apply_auslagen_freigabe(lines, ["AUS", "DUR"])
    assert [ln["classifiedtaxcategorypercent"] for ln in lines] == ["0", "0"]


def test_nicht_freigegebener_artikel_ohne_steuer_blockt():
    """Live-Befund: Getraenke (RE1) ohne Steuerbuchung duerfen nicht als 0 % raus."""
    from modules import invoice_enrich as ie
    inv = _auslagen_rechnung()
    inv["lines"].append(_ohne_steuer("RE1"))
    ie.apply_auslagen_freigabe(inv["lines"], ["AUS", "DUR"])
    issues = invoice_validator.validate(inv)
    err = [i for i in issues if i["field"].endswith("tax_missing")]
    assert len(err) == 1 and err[0]["severity"] == "error"
    assert "RE1" in err[0]["message"] and "Getraenke Spaet" in err[0]["message"]
    assert not [i for i in issues if i["field"].endswith("tax_percent")]


def test_paidout_braucht_keine_freigabe():
    from modules import invoice_enrich as ie
    ln = _ohne_steuer("AUS"); ln["ispaidout"] = 1; ln["itemshortdesc"] = "XYZ"
    ie.apply_auslagen_freigabe([ln], [])
    assert ln["classifiedtaxcategorypercent"] == "0"


def test_freigabeliste_aus_hotel_json(monkeypatch):
    from modules import invoice_fetcher
    monkeypatch.setattr(invoice_fetcher, "load_json", lambda p, default=None: {})
    assert invoice_fetcher._auslagen_artikel() == ["AUS", "DUR"]
    monkeypatch.setattr(invoice_fetcher, "load_json", lambda p, default=None: {"auslagen_artikel": ["AUS"]})
    assert invoice_fetcher._auslagen_artikel() == ["AUS"]


def test_fetch_invoice_wendet_freigabe_an():
    import inspect
    from modules import invoice_fetcher
    assert "apply_auslagen_freigabe(lines, _auslagen_artikel())" in inspect.getsource(invoice_fetcher.fetch_invoice)


# --- Review zu Paid-Out ---

def test_paidout_kategorie_immer_z():
    """Paid-Out mit TAXLINK auf eine Steuerzeile darf nicht 'S' mit 0 % werden."""
    for name in ("lines", "totals"):
        assert "decode(z.zpos_cdt,5,'z',decode(" in _flat(name), name
    # invoice_tax.sql gruppiert nach Steuercode: Paid-Out erbt keinen
    assert "decode(z.zpos_cdt,5,to_number(null),(selectz3.zpos_ztcd_id" in _flat("tax")


def test_paidout_nur_sichtbar_und_unverteilt():
    for name in ("lines", "tax", "totals"):
        assert ("z.zpos_paidout=1andnvl(z.zpos_hidden,0)=0andnvl(z.zpos_zall_id,0)=0" in _flat(name)), name


def test_alter_override_ohne_paidout_gilt_als_veraltet():
    from modules.invoice_fetcher import _stale_override_markers
    alt = "... Z3.zpos_cdt=2 ... DepositZinvId OriginYresId LineExtensionAmountVat_number ClassifiedTaxCategoryZtcdId"
    for name in ("invoice_lines.sql", "invoice_tax.sql", "invoice_totals.sql"):
        assert _stale_override_markers(name, alt), name


def test_ohne_taxlink_nur_der_allgemeine_fehler():
    inv = _auslagen_rechnung()
    ln = inv["lines"][2]
    ln["taxlinecount"] = 0
    ln["classifiedtaxcategorypercent"] = None   # ohne TAXLINK -> Fehler
    issues = invoice_validator.validate(inv)
    assert [i for i in issues if i["field"].endswith("tax_percent")]
    assert not [i for i in issues if i["field"].endswith("tax_missing")]


# --- Review zur Freigabeliste ---

def test_stornierte_fehlbuchung_ohne_steuer_blockt_nicht():
    """+9,80 / -9,80 RE1 ohne Steuer: netto nichts uebrig -> kein Block."""
    from modules import invoice_enrich as ie
    a, b = _ohne_steuer("RE1"), _ohne_steuer("RE1")
    b["lineextensionamount"] = b["lineextensionamountnet"] = "-9.80"
    ie.apply_auslagen_freigabe([a, b], ["AUS"])
    assert not a.get("taxmissing") and not b.get("taxmissing")


def test_freigabeliste_als_text(monkeypatch):
    from modules import invoice_fetcher
    monkeypatch.setattr(invoice_fetcher, "load_json", lambda p, default=None: {"auslagen_artikel": "AUS, DUR"})
    assert invoice_fetcher._auslagen_artikel() == ["AUS", "DUR"]


def test_meldung_nennt_artikel_zuerst():
    from modules import invoice_enrich as ie
    inv = _auslagen_rechnung()
    inv["lines"].append(_ohne_steuer("RE1"))
    ie.apply_auslagen_freigabe(inv["lines"], ["AUS"])
    msg = next(i["message"] for i in invoice_validator.validate(inv) if i["field"] == "lines.tax_missing")
    assert "RE1" in msg[:40]


def test_marker_fuer_artikelkurzname():
    from modules.invoice_fetcher import _EXPECTED_OVERRIDE_MARKERS
    assert "ItemShortDesc" in _EXPECTED_OVERRIDE_MARKERS["invoice_lines.sql"]
