"""Tests: Kaeuferadresse aus Strasse 1/2/3 (BT-50, BT-51, BT-163).

Suite8 kennt drei Strassenzeilen (XADR_STREET1..3). Es kommt vor, dass Zeile 1
leer und Zeile 2 gefuellt ist. Leere Zeilen fallen weg, die uebrigen ruecken
nach oben: 1. -> StreetName, 2. -> AdditionalStreetName, 3. -> AddressLine.
"""
import pytest
from lxml import etree

from modules import invoice_enrich as ie
from modules import xml_builder
from tests_slim.test_deposit_allowances import _invoice, _line
from tests_slim.test_creditnote_xsd import _CN_XSD, _INV_XSD, _assert_xsd_valid, _base_invoice

NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}


def test_leere_zeilen_ruecken_nach_oben():
    assert ie.street_lines(None, "Hinterhaus", "  ") == ["Hinterhaus"]
    assert ie.street_lines("", "Postfach 1", "Etage 3") == ["Postfach 1", "Etage 3"]
    assert ie.street_lines(" Kundenweg 2 ", None, None) == ["Kundenweg 2"]


def test_drei_zeilen_auf_bt50_51_163():
    h = {"customeradrstreet1": "Kundenweg 2", "customeradrstreet2": "Haus B",
         "customeradrstreet3": "c/o Einkauf", "customerstreetname": "Kundenweg 2"}
    ie.apply_customer_address(h)
    assert (h["customerstreetname"], h["customeradditionalstreetname"],
            h["customeraddressline"]) == ("Kundenweg 2", "Haus B", "c/o Einkauf")


def test_zeile1_leer_zeile2_wird_strasse():
    h = {"customeradrstreet1": "  ", "customeradrstreet2": "Am Markt 5",
         "customeradrstreet3": None, "customerstreetname": "Primaerweg 9"}
    ie.apply_customer_address(h)
    assert h["customerstreetname"] == "Am Markt 5"
    assert h["customeradditionalstreetname"] is None
    assert h["customeraddressline"] is None


def test_rechnungsadresse_leer_nimmt_primaeradresse():
    h = {"customeradrstreet1": None, "customeradrstreet2": None, "customeradrstreet3": None,
         "customerprimstreet1": None, "customerprimstreet2": "Am Markt 5",
         "customerprimstreet3": None, "customerstreetname": None}
    ie.apply_customer_address(h)
    assert h["customerstreetname"] == "Am Markt 5"
    assert h["customeradditionalstreetname"] is None


def test_alles_leer_strasse_bleibt_unveraendert():
    h = {"customeradrstreet1": None, "customeradrstreet2": "", "customeradrstreet3": None,
         "customerprimstreet1": None, "customerprimstreet2": None,
         "customerprimstreet3": None, "customerstreetname": None}
    ie.apply_customer_address(h)
    assert h["customerstreetname"] is None


def test_ohne_neue_spalten_bleibt_alles_wie_bisher():
    """SQL-Override ohne die neuen Spalten: Verhalten wie vor dem Umbau."""
    h = {"customerstreetname": "Kundenweg 2"}
    ie.apply_customer_address(h)
    assert h["customerstreetname"] == "Kundenweg 2"
    assert h.get("customeradditionalstreetname") is None


def _doc(role, **header):
    """role 0: positive Rechnung (Invoice), role 3: Gutschrift (CreditNote)."""
    if role == 0:
        inv = _invoice([_line("Uebernachtung", 107.00, 100.00, 7)], gross=107.00, net=100.00, tax=7.00)
    else:
        inv = _base_invoice(3)
    inv["header"].update(header)
    return inv


def _customer_address(xml: bytes):
    doc = etree.fromstring(xml)
    return doc.find("cac:AccountingCustomerParty/cac:Party/cac:PostalAddress", NS)


@pytest.mark.parametrize("role,xsd", [(0, _INV_XSD), (3, _CN_XSD)])
def test_xml_zusatz_ohne_adresszeile(role, xsd):
    inv = _doc(role, customeradditionalstreetname="Haus B", customeraddressline=None)
    xml = xml_builder.render(inv)
    adr = _customer_address(xml)
    assert adr.findtext("cbc:AdditionalStreetName", namespaces=NS) == "Haus B"
    assert adr.find("cac:AddressLine", NS) is None
    _assert_xsd_valid(xml, xsd)


@pytest.mark.parametrize("role,xsd", [(0, _INV_XSD), (3, _CN_XSD)])
def test_xml_adresszeile_nach_plz_vor_land(role, xsd):
    inv = _doc(role, customeradditionalstreetname="Haus B",
                        customeraddressline="c/o Einkauf & Co")
    xml = xml_builder.render(inv)
    adr = _customer_address(xml)
    tags = [etree.QName(el).localname for el in adr]
    assert tags == ["StreetName", "AdditionalStreetName", "CityName", "PostalZone",
                    "AddressLine", "Country"]
    assert adr.findtext("cac:AddressLine/cbc:Line", namespaces=NS) == "c/o Einkauf & Co"
    _assert_xsd_valid(xml, xsd)


@pytest.mark.parametrize("role", [0, 3])
def test_xml_ohne_zusatz_keine_leeren_elemente(role):
    xml = xml_builder.render(_doc(role))
    adr = _customer_address(xml)
    assert adr.find("cbc:AdditionalStreetName", NS) is None
    assert adr.find("cac:AddressLine", NS) is None


def test_header_sql_liefert_drei_strassenzeilen_und_marker():
    from pathlib import Path
    from modules.invoice_fetcher import _EXPECTED_OVERRIDE_MARKERS
    sql = (Path(__file__).resolve().parent.parent / "sql" / "invoice_header.sql").read_text(encoding="utf-8")
    for col in ("CustomerAdrStreet1", "CustomerAdrStreet2", "CustomerAdrStreet3",
                "CustomerPrimStreet1", "CustomerPrimStreet2", "CustomerPrimStreet3"):
        assert col in sql
    assert "xadr_street3" in sql.lower()
    assert "CustomerAdrStreet2" in _EXPECTED_OVERRIDE_MARKERS["invoice_header.sql"]


def test_fetch_invoice_wendet_adresse_an():
    import inspect
    from modules import invoice_fetcher
    assert "apply_customer_address" in inspect.getsource(invoice_fetcher.fetch_invoice)
