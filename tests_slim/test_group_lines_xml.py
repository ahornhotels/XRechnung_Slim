"""Tests: Positionshinweis (BT-127), Positionszeitraum (BT-134/135), Preis mit
4 Nachkommastellen und Menge in Rechnung und Gutschrift."""
from decimal import Decimal

import pytest
from lxml import etree

from modules import invoice_enrich as ie
from modules import xml_builder
from tests_slim.test_creditnote_xsd import _CN_XSD, _INV_XSD, _assert_xsd_valid, _base_invoice
from tests_slim.test_group_lines import _b, _rechnung

NS = {"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
      "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"}


def _gruppe():
    lines = [_b(gross=33.35, net=31.17, day=d) for d in ("2026-03-02", "2026-03-03", "2026-03-04")]
    lines += [_b(yres=2, xcms=2, name="Max Beispiel", room="102", day="2026-03-05")]
    inv = _rechnung(ie.group_lines(lines, merge=True))
    inv["header"].update(startdate="2026-03-02", enddate="2026-03-04")
    ie.extend_invoice_period(inv["header"], inv["lines"])
    return inv


def test_position_reihenfolge_note_periode_preis():
    xml = xml_builder.render(_gruppe())
    doc = etree.fromstring(xml)
    first = doc.find("cac:InvoiceLine", NS)
    tags = [etree.QName(el).localname for el in first]
    assert tags[:5] == ["ID", "Note", "InvoicedQuantity", "LineExtensionAmount", "InvoicePeriod"]
    assert first.findtext("cbc:Note", namespaces=NS) == "Zi. 101 · Erika Muster"
    assert first.findtext("cbc:InvoicedQuantity", namespaces=NS) == "3"
    assert first.findtext("cac:Price/cbc:PriceAmount", namespaces=NS) == "31.17"
    assert (first.findtext("cac:InvoicePeriod/cbc:StartDate", namespaces=NS),
            first.findtext("cac:InvoicePeriod/cbc:EndDate", namespaces=NS)) == ("2026-03-02", "2026-03-04")
    assert doc.findtext("cac:InvoicePeriod/cbc:EndDate", namespaces=NS) == "2026-03-05"
    _assert_xsd_valid(xml, _INV_XSD)


def test_preis_mit_vier_nachkommastellen():
    assert xml_builder._price4("33.3333") == "33.3333"
    assert xml_builder._price4("31.1700") == "31.17"
    assert xml_builder._price4("31.1750") == "31.175"
    assert xml_builder._price4(None) == "0.00"


def test_ohne_gruppe_kein_note_element():
    inv = _rechnung(ie.group_lines([_b(), _b(day="2026-03-03")], merge=True))
    doc = etree.fromstring(xml_builder.render(inv))
    assert doc.find("cac:InvoiceLine/cbc:Note", NS) is None


def test_gutschrift_menge_positiv_und_xsd():
    """Storno zusammengefasst: Menge -3, Betrag negativ -> CreditNote mit 3 und positiv."""
    lines = [_b(gross=-107.0, net=-100.0, qty=-1, unit=107.0, day=d) for d in ("2026-03-02", "2026-03-03", "2026-03-04")]
    inv = _base_invoice(3)
    inv["lines"] = ie.group_lines(lines, merge=True)
    inv["tax_breakdown"] = [{"taxcategoryid": "S", "taxcategorypercent": "7.00",
                             "taxableamount": "-300.00", "taxamount": "-21.00"}]
    inv["totals"] = {"invoicegross": -321.0, "invoicenet": -300.0, "invoicetaxtotal": -21.0, "spay_cl": 0}
    xml = xml_builder.render(inv)
    doc = etree.fromstring(xml)
    ln = doc.find("cac:CreditNoteLine", NS)
    qty = Decimal(ln.findtext("cbc:CreditedQuantity", namespaces=NS))
    price = Decimal(ln.findtext("cac:Price/cbc:PriceAmount", namespaces=NS))
    amount = Decimal(ln.findtext("cbc:LineExtensionAmount", namespaces=NS))
    assert qty == 3 and (qty * price).quantize(Decimal("0.01")) == amount == Decimal("300.00")
    assert ln.find("cac:InvoicePeriod", NS) is not None
    _assert_xsd_valid(xml, _CN_XSD)


def test_gemischte_gutschrift_summe_stimmt():
    """3 x Storno -100 plus +100 Bar: Positionssumme muss BT-106 (200) ergeben."""
    lines = [_b(gross=-107.0, net=-100.0, qty=-1, unit=107.0, day=d) for d in ("2026-03-02", "2026-03-03", "2026-03-04")]
    lines.append(_b(item="Bar", gross=107.0, net=100.0, code="BAR"))
    inv = _base_invoice(3)
    inv["lines"] = ie.group_lines(lines, merge=True)
    inv["tax_breakdown"] = [{"taxcategoryid": "S", "taxcategorypercent": "7.00",
                             "taxableamount": "-200.00", "taxamount": "-14.00"}]
    inv["totals"] = {"invoicegross": -214.0, "invoicenet": -200.0, "invoicetaxtotal": -14.0, "spay_cl": 0}
    doc = etree.fromstring(xml_builder.render(inv))
    total = Decimal(doc.findtext("cac:LegalMonetaryTotal/cbc:LineExtensionAmount", namespaces=NS))
    lines_sum = sum(Decimal(l.findtext("cbc:LineExtensionAmount", namespaces=NS))
                    for l in doc.findall("cac:CreditNoteLine", NS))
    assert lines_sum == total == Decimal("200.00")
    for l in doc.findall("cac:CreditNoteLine", NS):
        q = Decimal(l.findtext("cbc:CreditedQuantity", namespaces=NS))
        p = Decimal(l.findtext("cac:Price/cbc:PriceAmount", namespaces=NS))
        assert p >= 0 and (q * p).quantize(Decimal("0.01")) == Decimal(l.findtext("cbc:LineExtensionAmount", namespaces=NS))


def test_storno_datum_verlaengert_rechnungszeitraum_nicht():
    h = {"startdate": "2026-03-02", "enddate": "2026-03-04"}
    lines = ie.group_lines([_b(), _b(gross=-107.0, net=-100.0, qty=-1, unit=107.0, day="2026-03-10")], merge=True)
    ie.extend_invoice_period(h, lines)
    assert h["enddate"] == "2026-03-04"
