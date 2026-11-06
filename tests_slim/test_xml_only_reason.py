"""Tests: Wann gilt Nur-XML-Versand? Globaler Schalter oder Membership 'PDF'."""
import logging

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


def _cfg(monkeypatch, **hotel):
    monkeypatch.setattr(invoice_fetcher, "load_json", lambda p, default=None: hotel)
    monkeypatch.setattr(invoice_fetcher, "_warned_xml_only_query", False)


def test_standard_pdf_und_xml(monkeypatch):
    _cfg(monkeypatch)
    cur = _Cur(row=None)
    assert invoice_fetcher._xml_only_reason(cur, 5) is None


def test_membership_pdf_nur_xml(monkeypatch):
    _cfg(monkeypatch)
    cur = _Cur(row=(1,))
    assert invoice_fetcher._xml_only_reason(cur, 5) == "membership"
    sql, params = cur.calls[0]
    assert params == {"zinv_id": 5, "code": "PDF"}
    for part in ("XMNR", "XMTY", "upper(xmty_shortdesc)=upper(:code)", "zwin_invoice_to_xcms_id", "zinv_xcms_id"):
        assert part.lower() in sql.lower(), part


def test_eigener_membership_code(monkeypatch):
    _cfg(monkeypatch, xml_only_membership="NURXML")
    cur = _Cur(row=(1,))
    invoice_fetcher._xml_only_reason(cur, 5)
    assert cur.calls[0][1]["code"] == "NURXML"


def test_globaler_schalter_ohne_abfrage(monkeypatch):
    _cfg(monkeypatch, xml_only_all=True)
    cur = _Cur(row=None)
    assert invoice_fetcher._xml_only_reason(cur, 5) == "global"
    assert cur.calls == []


def test_leerer_code_keine_abfrage(monkeypatch):
    _cfg(monkeypatch, xml_only_membership="")
    cur = _Cur(row=(1,))
    assert invoice_fetcher._xml_only_reason(cur, 5) is None and cur.calls == []


def test_db_fehler_pdf_bleibt_und_warnt(monkeypatch, caplog):
    _cfg(monkeypatch)
    cur = _Cur(error=Exception("ORA-00942: table or view does not exist"))
    with caplog.at_level(logging.WARNING):
        assert invoice_fetcher._xml_only_reason(cur, 5) is None
    assert "Nur-XML" in caplog.text


def test_fetch_invoice_setzt_xml_only():
    import inspect
    src = inspect.getsource(invoice_fetcher.fetch_invoice)
    assert '"xml_only": _xml_only_reason(cur, zinv_id)' in src


def test_hotel_json_example_schalter():
    import json
    from pathlib import Path
    ex = json.loads((Path(__file__).resolve().parent.parent / "slim" / "config" / "hotel.json.example").read_text(encoding="utf-8"))
    assert ex["xml_only_all"] is False and ex["xml_only_membership"] == "PDF"
