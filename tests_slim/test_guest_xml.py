"""Tests: BT-44 nur Rechnungsempfaenger, Gast in BT-22 und BT-70 (Delivery)."""
import pytest
from lxml import etree

from modules import xml_builder
from tests_slim.test_creditnote_xsd import _CN_XSD, _INV_XSD, _assert_xsd_valid, _base_invoice
from tests_slim.test_deposit_allowances import _invoice, _line

NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}
NOTE = "Gast: Erika Muster, Zimmer 101, 02.03.2026 bis 05.03.2026"


def _doc(role, **header):
    if role == 0:
        inv = _invoice([_line("Uebernachtung", 107.00, 100.00, 7)], gross=107.00, net=100.00, tax=7.00)
    else:
        inv = _base_invoice(3)
    inv["header"].update(header)
    return inv


def _root(inv):
    xml = xml_builder.render(inv)
    return xml, etree.fromstring(xml)


@pytest.mark.parametrize("role", [0, 3])
def test_bt44_ist_rechnungsempfaenger_nicht_gast(role):
    _, doc = _root(_doc(role, customername="Kunde AG", customerregistrationname="Erika Muster"))
    reg = doc.findtext("cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName",
                       namespaces=NS)
    assert reg == "Kunde AG"


@pytest.mark.parametrize("role,xsd", [(0, _INV_XSD), (3, _CN_XSD)])
def test_bt70_und_bt22_bei_einem_gast(role, xsd):
    xml, doc = _root(_doc(role, note=NOTE, deliverypartyname="Erika Muster"))
    assert doc.findtext("cbc:Note", namespaces=NS) == NOTE
    assert doc.findtext("cac:Delivery/cac:DeliveryParty/cac:PartyName/cbc:Name",
                        namespaces=NS) == "Erika Muster"
    _assert_xsd_valid(xml, xsd)


@pytest.mark.parametrize("role", [0, 3])
def test_ohne_gast_kein_delivery_element(role):
    _, doc = _root(_doc(role, deliverypartyname=None))
    assert doc.find("cac:Delivery", NS) is None


@pytest.mark.parametrize("role,xsd", [(0, _INV_XSD), (3, _CN_XSD)])
def test_sonderzeichen_bleiben_wohlgeformt(role, xsd):
    name = "Müller & Söhne <GmbH>"
    note = f"Tagung & Co · Gast: {name}"
    xml, doc = _root(_doc(role, note=note, deliverypartyname=name))
    assert doc.findtext("cbc:Note", namespaces=NS) == note
    assert doc.findtext("cac:Delivery/cac:DeliveryParty/cac:PartyName/cbc:Name", namespaces=NS) == name
    _assert_xsd_valid(xml, xsd)
