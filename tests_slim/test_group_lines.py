"""Tests: Positionen zusammenfassen und Gruppenrechnung je Gast und Zimmer."""
from decimal import Decimal
from pathlib import Path

from modules import invoice_enrich as ie
from modules.invoice_fetcher import _EXPECTED_OVERRIDE_MARKERS

SQL = (Path(__file__).resolve().parent.parent / "sql" / "invoice_lines.sql").read_text(encoding="utf-8")


def test_sql_liefert_menge_einzelpreis_buchungsdatum():
    for col in ("Quantity", "GrossUnitPrice", "PostDate"):
        assert f" {col}," in SQL or f" {col}\n" in SQL, col
    assert "z.zpos_quantity*decode(z.zpos_cdt,5,-1,1) Quantity" in SQL
    assert "GrossUnitPrice" in _EXPECTED_OVERRIDE_MARKERS["invoice_lines.sql"]
