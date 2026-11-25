"""Tests (nur Kanal AHORN): Voucher-Nummer des Reiseveranstalters als BT-13.

Suite8 fuehrt die Voucher-Nummer an der Reservierung (YRCF_VOUCHERNO). Fuer
die Abrechnung mit Reiseveranstaltern kommt sie als Bestellnummer des Kaeufers
(BT-13, cac:OrderReference/cbc:ID) in die XRechnung. Eine Sammelrechnung ueber
mehrere Reservierungen traegt alle Nummern, durch Komma getrennt.
"""
from lxml import etree

from modules import invoice_fetcher, xml_builder
from tests_slim.test_creditnote_xsd import _CN_XSD, _INV_XSD, _assert_xsd_valid, _base_invoice
from tests_slim.test_deposit_allowances import _invoice, _line

NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}


class _Cur:
    def __init__(self, rows=None, fehler=None):
        self.rows, self.fehler, self.sql = rows or [], fehler, None

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params
        if self.fehler:
            raise self.fehler

    def fetchall(self):
        return self.rows


def _rechnung(**kopf):
    """Normale Rechnung: eine Position Logis, 100,00 netto zu 7 %."""
    inv = _invoice([_line("Logis", 107.0, 100.0, 7)], 107.0, 100.0, 7.0)
    inv["header"].update(kopf)
    return inv


def _bt13(xml: bytes):
    doc = etree.fromstring(xml)
    return [e.text for e in doc.findall("cac:OrderReference/cbc:ID", NS)]


def test_eine_voucher_nummer_wird_gelesen():
    cur = _Cur([("  TUI123456 ",)])
    assert invoice_fetcher._voucher_nummern(cur, 4711) == "TUI123456"
    assert cur.params == {"zinv_id": 4711}
    assert "YRCF_VOUCHERNO" in cur.sql.upper()


def test_mehrere_voucher_ohne_doppelte_und_leere():
    cur = _Cur([("B2",), ("A1",), (" A1",), (None,), ("  ",)])
    assert invoice_fetcher._voucher_nummern(cur, 1) == "A1, B2"


def test_keine_voucher_nummer_ergibt_none():
    assert invoice_fetcher._voucher_nummern(_Cur([]), 1) is None


def test_fehlende_spalte_blockiert_die_rechnung_nicht():
    cur = _Cur(fehler=Exception('ORA-00904: "C"."YRCF_VOUCHERNO": invalid identifier'))
    assert invoice_fetcher._voucher_nummern(cur, 1) is None


def test_rechnung_mit_voucher_hat_bt13_und_bleibt_schemagueltig():
    xml = xml_builder.render(_rechnung(orderreferenceid="TUI123456"))
    assert _bt13(xml) == ["TUI123456"]
    _assert_xsd_valid(xml, _INV_XSD)


def test_rechnung_ohne_voucher_hat_kein_bt13():
    xml = xml_builder.render(_rechnung())
    assert _bt13(xml) == []
    _assert_xsd_valid(xml, _INV_XSD)


def test_gutschrift_mit_voucher_hat_bt13_und_bleibt_schemagueltig():
    inv = _base_invoice(3, orderreferenceid="TUI123456")
    xml = xml_builder.render(inv)
    assert _bt13(xml) == ["TUI123456"]
    _assert_xsd_valid(xml, _CN_XSD)


def test_sonderzeichen_im_voucher_werden_maskiert():
    assert _bt13(xml_builder.render(_rechnung(orderreferenceid="A&B<1>"))) == ["A&B<1>"]
