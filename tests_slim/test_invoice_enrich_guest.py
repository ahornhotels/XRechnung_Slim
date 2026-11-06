"""Tests: Gastzeile in BT-22 (und Gastname fuer BT-70), nur bei genau einem Gast.

Gast je Buchung = (Herkunftsreservierung, Gastprofil) aus ZPOS_ORIGINATED_*.
Bei mehreren Gaesten (Reisegruppe) entfaellt die Kopfzeile, weil sie nur einen
von ihnen nennen wuerde. Buchungen ohne Herkunft (Finanzkonto) zaehlen nicht.
"""
from modules import invoice_enrich as ie
from modules import invoice_fetcher

G = {"gast": "Erika Muster", "zimmer": "101", "anreise": "02.03.2026", "abreise": "05.03.2026"}


def _ln(yres=11, xcms=21, name="Erika Muster", room="101",
        arr="2026-03-02", dep="2026-03-05", deposit=None):
    return {"itemname": "Logis", "originyresid": yres, "originxcmsid": xcms,
            "originguestname": name, "originroom": room,
            "originarrival": arr, "origindeparture": dep, "depositzinvid": deposit}


def _inv(lines, note=None):
    return {"header": {"note": note}, "lines": lines}


def test_gastzeile_standard():
    assert ie.guest_line(ie.GASTZEILE_STANDARD, G) == \
        "Gast: Erika Muster, Zimmer 101, 02.03.2026 bis 05.03.2026"


def test_fehlendes_zimmer_nur_dieser_teil_entfaellt():
    assert ie.guest_line(ie.GASTZEILE_STANDARD, {**G, "zimmer": None}) == \
        "Gast: Erika Muster, 02.03.2026 bis 05.03.2026"


def test_fehlende_abreise_zeitraum_entfaellt():
    assert ie.guest_line(ie.GASTZEILE_STANDARD, {**G, "abreise": ""}) == \
        "Gast: Erika Muster, Zimmer 101"


def test_ohne_gast_oder_leere_vorlage_keine_zeile():
    assert ie.guest_line(ie.GASTZEILE_STANDARD, {**G, "gast": None}) is None
    assert ie.guest_line(ie.GASTZEILE_STANDARD, {**G, "gast": "  "}) is None
    assert ie.guest_line("", G) is None


def test_guests_datum_deutsch_und_ohne_anzahlung():
    gs = ie.guests([_ln(), _ln(), _ln(yres=99, xcms=98, deposit=4711)])
    assert gs == [G]


def test_ein_gast_setzt_note_und_bt70():
    inv = _inv([_ln(), _ln()])
    ie.apply_guest_info(inv, ie.GASTZEILE_STANDARD)
    assert inv["header"]["note"] == "Gast: Erika Muster, Zimmer 101, 02.03.2026 bis 05.03.2026"
    assert inv["header"]["deliverypartyname"] == "Erika Muster"


def test_vorhandener_hinweis_wird_angehaengt():
    inv = _inv([_ln()], note="Tagung Vertrieb")
    ie.apply_guest_info(inv, ie.GASTZEILE_STANDARD)
    assert inv["header"]["note"] == \
        "Tagung Vertrieb · Gast: Erika Muster, Zimmer 101, 02.03.2026 bis 05.03.2026"


def test_mehrere_gaeste_keine_kopfzeile():
    inv = _inv([_ln(), _ln(yres=12, xcms=22, name="Max Beispiel", room="102")], note="Tagung")
    ie.apply_guest_info(inv, ie.GASTZEILE_STANDARD)
    assert inv["header"]["note"] == "Tagung"
    assert inv["header"]["deliverypartyname"] is None


def test_mitreisender_eigenes_profil_zaehlt_als_zweiter_gast():
    lines = [_ln(), _ln(xcms=23, name="Max Beispiel")]
    assert len(ie.guests(lines)) == 2
    inv = _inv(lines)
    ie.apply_guest_info(inv, ie.GASTZEILE_STANDARD)
    assert inv["header"]["note"] is None


def test_nur_kontobuchungen_ohne_herkunft():
    lines = [_ln(yres=None, name="Firmenkonto"), _ln(yres=None)]
    assert ie.guests(lines) == []
    inv = _inv(lines)
    ie.apply_guest_info(inv, ie.GASTZEILE_STANDARD)
    assert inv["header"]["note"] is None
    assert inv["header"]["deliverypartyname"] is None


def test_kontobuchung_neben_einem_gast_zaehlt_nicht():
    inv = _inv([_ln(), _ln(yres=None, xcms=55, name="Firmenkonto")])
    ie.apply_guest_info(inv, ie.GASTZEILE_STANDARD)
    assert inv["header"]["note"].startswith("Gast: Erika Muster")


def test_gast_ohne_namen_keine_zeile():
    inv = _inv([_ln(name=None)])
    ie.apply_guest_info(inv, ie.GASTZEILE_STANDARD)
    assert inv["header"]["note"] is None
    assert inv["header"]["deliverypartyname"] is None


def test_gastzeile_vorlage_aus_hotel_json(monkeypatch):
    monkeypatch.setattr(invoice_fetcher, "load_json", lambda p, default=None: {})
    assert invoice_fetcher._gastzeile_template() == ie.GASTZEILE_STANDARD
    monkeypatch.setattr(invoice_fetcher, "load_json", lambda p, default=None: {"gastzeile": ""})
    assert invoice_fetcher._gastzeile_template() == ""
    monkeypatch.setattr(invoice_fetcher, "load_json",
                        lambda p, default=None: {"gastzeile": "Gast: {gast}"})
    assert invoice_fetcher._gastzeile_template() == "Gast: {gast}"


def test_hotel_json_example_enthaelt_gastzeile():
    import json
    from pathlib import Path
    ex = Path(__file__).resolve().parent.parent / "slim" / "config" / "hotel.json.example"
    assert json.loads(ex.read_text(encoding="utf-8"))["gastzeile"] == ie.GASTZEILE_STANDARD
