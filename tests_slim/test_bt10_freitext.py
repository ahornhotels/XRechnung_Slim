"""Tests: BT-10 (Kaeuferreferenz) aus ZWIN-Freitext 1-4. Ein eingeschalteter,
gefuellter Freitext hat Vorrang vor der DXR-Mitgliedschaft."""
import logging
from contextlib import contextmanager

from modules import invoice_fetcher


class _Cur:
    def __init__(self, row=None, error=None):
        self.row, self.error, self.calls = row, error, []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))
        if self.error:
            raise self.error

    def fetchone(self):
        return self.row


def test_freitext_hat_vorrang_vor_dxr():
    cur = _Cur(row=("LEITWEG-1", "A", "B", None, None))
    assert invoice_fetcher._buyer_reference_aus_freitext(cur, 7, [1, 2]) == "A"


def test_dxr_bleibt_wenn_eingeschaltete_freitexte_leer():
    cur = _Cur(row=("LEITWEG-1", "  ", None, "C", None))
    assert invoice_fetcher._buyer_reference_aus_freitext(cur, 7, [1, 2]) is None


def test_dxr_bleibt_wenn_gefuellter_freitext_nicht_eingeschaltet():
    cur = _Cur(row=("LEITWEG-1", "A", None, None, None))
    assert invoice_fetcher._buyer_reference_aus_freitext(cur, 7, [2, 3]) is None


def test_erster_gefuellter_in_reihenfolge():
    cur = _Cur(row=(None, "  ", "B", "C", None))
    assert invoice_fetcher._buyer_reference_aus_freitext(cur, 7, [1, 2, 3]) == "B"


def test_leere_dxr_zaehlt_nicht():
    cur = _Cur(row=("  ", "A", None, None, None))
    assert invoice_fetcher._buyer_reference_aus_freitext(cur, 7, [1]) == "A"


def test_nur_eingeschaltete():
    cur = _Cur(row=(None, "A", "B", None, None))
    assert invoice_fetcher._buyer_reference_aus_freitext(cur, 7, [2]) == "B"


def test_wert_wird_getrimmt():
    cur = _Cur(row=(None, None, None, None, "  PO-1  "))
    assert invoice_fetcher._buyer_reference_aus_freitext(cur, 7, [4]) == "PO-1"


def test_keiner_gefuellt():
    cur = _Cur(row=(None, None, "", None, None))
    assert invoice_fetcher._buyer_reference_aus_freitext(cur, 7, [1, 2, 3, 4]) is None


def test_keine_zeile():
    assert invoice_fetcher._buyer_reference_aus_freitext(_Cur(row=None), 7, [1]) is None


def test_nichts_aktiv_keine_abfrage():
    cur = _Cur(row=(None, "A", None, None, None))
    assert invoice_fetcher._buyer_reference_aus_freitext(cur, 7, []) is None
    assert cur.calls == []


def test_sql_bindet_zinv_id_und_nutzt_dxr():
    cur = _Cur(row=None)
    invoice_fetcher._buyer_reference_aus_freitext(cur, 7, [1])
    sql, params = cur.calls[0]
    assert params == {"zinv_id": 7}
    for part in ("xmty_shortdesc = 'DXR'", "xmnr_xcms_id = zwin_invoice_to_xcms_id",
                 "zwin_freetext1", "zwin_freetext4"):
        assert part in sql, part


def test_abfragefehler_ergibt_none(caplog):
    cur = _Cur(error=RuntimeError("ORA-00904"))
    with caplog.at_level(logging.WARNING):
        assert invoice_fetcher._buyer_reference_aus_freitext(cur, 7, [1]) is None
    assert "ORA-00904" in caplog.text


def test_einstellung_lesen(monkeypatch):
    monkeypatch.setattr(invoice_fetcher, "load_json", lambda p, default=None: {
        "bt10_freitext3": True, "bt10_freitext1": True, "bt10_freitext2": False, "bt10_freitext4": "ja"})
    assert invoice_fetcher._bt10_freitexte() == [1, 3]


def test_einstellung_fehlt(monkeypatch):
    monkeypatch.setattr(invoice_fetcher, "load_json", lambda p, default=None: {})
    assert invoice_fetcher._bt10_freitexte() == []


def test_fetch_invoice_setzt_buyerreference(monkeypatch):
    rows = {"invoice_header.sql": ({"ID": "1", "BUYERREFERENCE": "Muster GmbH",
                                    "DOCUMENTCURRENCYCODE": "EUR"},),
            "invoice_lines.sql": (), "invoice_tax.sql": (), "invoice_totals.sql": ()}

    class _FCur:
        def execute(self, sql, params=None):
            self.sql = sql
            self.rows = next((r for k, r in rows.items() if sql == k), ())
            self.description = [(c,) for c in (self.rows[0].keys() if self.rows else ())]

        def fetchall(self):
            return [tuple(r.values()) for r in self.rows]

        def fetchone(self):
            if "zwin_freetext1" in self.sql:
                return ("LEITWEG-1", "Hinweis", "4711-0815", None, None)
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
    monkeypatch.setattr(invoice_fetcher, "_bt10_freitexte", lambda: [2, 3])
    h = invoice_fetcher.fetch_invoice(1)["header"]
    assert h["buyerreference"] == "4711-0815"
