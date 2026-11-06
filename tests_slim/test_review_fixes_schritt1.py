"""Regressionstests aus /code-review high zu Schritt 1 (Aufgaben 2 und 3)."""
from pathlib import Path

from modules import invoice_enrich as ie
from modules import invoice_fetcher

SQL = (Path(__file__).resolve().parent.parent / "sql" / "invoice_lines.sql").read_text(encoding="utf-8").lower()


def _ln(yres=11, xcms=21, name="Erika Muster", room="101"):
    return {"originyresid": yres, "originxcmsid": xcms, "originguestname": name,
            "originroom": room, "originarrival": "2026-03-02",
            "origindeparture": "2026-03-05", "depositzinvid": None}


# --- Aufgabe 2 ---

def test_zimmer_ohne_unaggregierte_einzelzeilen_abfrage():
    """Zwei YDET-Zeilen am selben Tag duerfen kein ORA-01427 ausloesen."""
    assert "t.ydet_date=trunc(z.zpos_postdate))" not in SQL.replace(" ", "")
    assert "dense_rank last" in SQL


def test_zimmer_vor_anreise_nimmt_erstes_zimmer():
    assert "dense_rank first" in SQL


def test_kontobuchung_bekommt_keine_reservierung():
    """Auf einem Finanzkonto entstandene Buchung: kein Gast/Zimmer (Spec 6)."""
    assert "zpos_originated_zfac_id" in SQL
    assert "ZPOS_ORIGINATED_ZFAC_ID" in invoice_fetcher._OPTIONAL_LINE_COLUMNS


def test_positionen_deterministisch_sortiert():
    assert "order by" in SQL.split("from\n(")[-1].rsplit(")", 1)[-1]


# --- Aufgabe 3 ---

def test_kaputte_vorlage_bricht_keine_rechnung():
    g = {"gast": "Erika Muster", "zimmer": "101", "anreise": "", "abreise": ""}
    assert ie.guest_line("Gast: {gast", g) is None
    assert ie.guest_line("Gast: {}", g) is None
    assert ie.guest_line("Gast: {gast:d}", g) is None


def test_vorlage_false_oder_null_schaltet_ab(monkeypatch):
    for value in (False, None, 0):
        monkeypatch.setattr(invoice_fetcher, "load_json",
                            lambda p, default=None, v=value: {"gastzeile": v})
        assert invoice_fetcher._gastzeile_template() == ""


def test_bt70_auch_ohne_gastzeile():
    inv = {"header": {"note": None}, "lines": [_ln()]}
    ie.apply_guest_info(inv, "")
    assert inv["header"]["note"] is None
    assert inv["header"]["deliverypartyname"] == "Erika Muster"


def test_ohne_originated_spalte_keine_gastangaben(monkeypatch):
    """Aeltere Suite8: Herkunft = Folio-Reservierung -> Master saehe wie EIN
    Gast aus. Dann lieber gar keine Gastangabe."""
    monkeypatch.setattr(invoice_fetcher, "_missing_line_columns", {"ZPOS_ORIGINATED_YRES_ID"})
    assert invoice_fetcher._guest_info_available() is False
    monkeypatch.setattr(invoice_fetcher, "_missing_line_columns", set())
    assert invoice_fetcher._guest_info_available() is True
