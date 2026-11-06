"""Tests: Herkunft je Buchung (ZPOS_ORIGINATED_*) in der Positions-SQL.

Gast und Zimmer je Buchung kommen aus ZPOS_ORIGINATED_XCMS_ID bzw. der
Herkunftsreservierung ZPOS_ORIGINATED_YRES_ID (Fallback ZPOS_YRES_ID), das
Zimmer aus YDET am Buchungstag. Aeltere Suite8-Versionen kennen die Spalten
evtl. nicht: dann laufen die Positionen ohne Herkunft, statt zu scheitern.
"""
from pathlib import Path

import pytest

from modules import invoice_fetcher
from modules.invoice_fetcher import _EXPECTED_OVERRIDE_MARKERS

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def test_lines_sql_liefert_herkunftsspalten():
    sql = (SQL_DIR / "invoice_lines.sql").read_text(encoding="utf-8")
    for col in ("OriginYresId", "OriginXcmsId", "OriginGuestName", "OriginRoom",
                "OriginArrival", "OriginDeparture"):
        assert col in sql
    assert "zpos_originated_yres_id" in sql.lower()
    assert "zpos_originated_xcms_id" in sql.lower()
    assert "OriginYresId" in _EXPECTED_OVERRIDE_MARKERS["invoice_lines.sql"]


class _Cursor:
    """Kennt die Spalten in `missing` nicht (ORA-00904)."""

    def __init__(self, missing):
        self.missing = {m.lower() for m in missing}
        self.sqls = []
        self.description = [("ITEMNAME",)]

    def execute(self, sql, params=None):
        self.sqls.append(sql)
        for col in sorted(self.missing):
            if f"z.{col}" in sql.lower():
                raise Exception(f'ORA-00904: "Z"."{col.upper()}": invalid identifier')

    def fetchall(self):
        return [("Uebernachtung",)]


def test_fehlende_originated_spalte_faellt_zurueck(monkeypatch):
    monkeypatch.setattr(invoice_fetcher, "_missing_line_columns", set())
    cur = _Cursor({"zpos_originated_yres_id"})
    assert invoice_fetcher._fetch_lines(cur, 1) == [{"itemname": "Uebernachtung"}]
    assert "ZPOS_ORIGINATED_YRES_ID" in invoice_fetcher._missing_line_columns
    assert len(cur.sqls) == 2
    assert "z.zpos_originated_yres_id" not in cur.sqls[1].lower()
    assert "z.zpos_deposit_zinv_id" in cur.sqls[1].lower()


def test_zwei_fehlende_spalten_nacheinander(monkeypatch):
    monkeypatch.setattr(invoice_fetcher, "_missing_line_columns", set())
    cur = _Cursor({"zpos_deposit_zinv_id", "zpos_originated_xcms_id"})
    assert invoice_fetcher._fetch_lines(cur, 1) == [{"itemname": "Uebernachtung"}]
    assert len(cur.sqls) == 3
    # Danach sofort die reduzierte Variante
    cur2 = _Cursor({"zpos_deposit_zinv_id", "zpos_originated_xcms_id"})
    invoice_fetcher._fetch_lines(cur2, 2)
    assert len(cur2.sqls) == 1


def test_andere_db_fehler_werden_nicht_geschluckt(monkeypatch):
    monkeypatch.setattr(invoice_fetcher, "_missing_line_columns", set())

    class _Kaputt(_Cursor):
        def execute(self, sql, params=None):
            raise Exception("ORA-00942: table or view does not exist")

    with pytest.raises(Exception, match="ORA-00942"):
        invoice_fetcher._fetch_lines(_Kaputt(set()), 1)
