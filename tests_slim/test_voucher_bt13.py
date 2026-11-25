"""Tests: Voucher-Nummer des Reiseveranstalters als BT-13 (einschaltbar).

Suite8 fuehrt die Voucher-Nummer an der Reservierung (YRCF_VOUCHERNO). Fuer
die Abrechnung mit Reiseveranstaltern kommt sie als Bestellnummer des Kaeufers
(BT-13, cac:OrderReference/cbc:ID) in die XRechnung. Eine Sammelrechnung ueber
mehrere Reservierungen traegt alle Nummern, durch Komma getrennt.

Eingeschaltet wird das unter Konfiguration XRechnung -> Bestellnummer (BT-13).
"""
from contextlib import contextmanager

from lxml import etree

from slim.core_slim import settings_schema

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


# ── Einstellung "Bestellnummer (BT-13)" ──

def test_einstellung_steht_auf_der_seite_xrechnung_und_ist_erklaert():
    sec = settings_schema.section("bestellnummer")
    assert sec.page == "xrechnung" and sec.label == "Bestellnummer (BT-13)"
    assert [s.key for s in sec.settings] == ["bt13_voucher"]
    s = sec.settings[0]
    assert s.type == "bool" and s.label == "Voucher-Nummer"
    assert s.default is invoice_fetcher.BT13_VOUCHER_STANDARD
    for wort in ("Bestellnummer", "Reiseveranstalter"):
        assert wort in s.help, wort
    for wort in ("Was ist BT-13", "Bestellnummer des Käufers", "Reiseveranstalter", "Voucher",
                 "Reservierung", "Komma", "BT-10", "Leitweg-ID"):
        assert wort in s.info, wort


def test_einstellung_lesen(monkeypatch):
    lies = lambda werte: (monkeypatch.setattr(invoice_fetcher, "load_json", lambda p, default=None: werte),
                          invoice_fetcher._bt13_voucher_aktiv())[1]
    assert lies({"bt13_voucher": True}) is True
    assert lies({"bt13_voucher": False}) is False
    assert lies({"bt13_voucher": "ja"}) is False          # nur echtes true zaehlt
    assert lies({}) is invoice_fetcher.BT13_VOUCHER_STANDARD


def _fetch(monkeypatch, aktiv):
    """fetch_invoice gegen eine Attrappe; liefert (Kopf, ausgefuehrte SQLs)."""
    rows = {"invoice_header.sql": ({"ID": "1", "BUYERREFERENCE": "Muster GmbH",
                                    "DOCUMENTCURRENCYCODE": "EUR"},)}
    sqls = []

    class _FCur:
        def execute(self, sql, params=None):
            sqls.append(sql)
            self.sql = sql
            self.rows = rows.get(sql, ())
            self.description = [(c,) for c in (self.rows[0].keys() if self.rows else ())]

        def fetchall(self):
            if "yrcf_voucherno" in self.sql:
                return [("TUI123456",)]
            return [tuple(r.values()) for r in self.rows]

        def fetchone(self):
            return None

    class _Conn:
        def cursor(self):
            return _FCur()

    @contextmanager
    def _fake_conn():
        yield _Conn()

    monkeypatch.setattr(invoice_fetcher, "get_connection", _fake_conn)
    monkeypatch.setattr(invoice_fetcher, "_read_sql", lambda name: name)
    monkeypatch.setattr(invoice_fetcher, "_resolve_billing_reference_from_payment", lambda c, h: None)
    monkeypatch.setattr(invoice_fetcher, "_bt10_freitexte", lambda: [])
    monkeypatch.setattr(invoice_fetcher, "_bt13_voucher_aktiv", lambda: aktiv)
    return invoice_fetcher.fetch_invoice(1)["header"], sqls


def test_eingeschaltet_kommt_die_voucher_nummer_in_den_kopf(monkeypatch):
    kopf, _ = _fetch(monkeypatch, True)
    assert kopf["orderreferenceid"] == "TUI123456"


def test_ausgeschaltet_wird_die_voucher_nummer_nicht_einmal_gelesen(monkeypatch):
    kopf, sqls = _fetch(monkeypatch, False)
    assert "orderreferenceid" not in kopf
    assert not any("yrcf_voucherno" in s for s in sqls)
