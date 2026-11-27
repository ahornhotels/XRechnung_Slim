"""Tests: Welche Rechnung bekommt eine XRechnung? Karteityp des Empfaengers und
Mindestbetrag, je Haus einstellbar. Ausgefilterte Mails gibt der Poller sofort
frei (nur PDF)."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules import xrechnung_filter as xf
from slim.core_slim import settings_schema
from slim.jobs_slim import poller


def _inv(typ=1, brutto="500.00", code="380", **extra):
    return {"header": {"invoicetypecode": code, "id": "900001"}, "karteityp": typ,
            "totals": {"invoicegross": brutto}, "lines": [], **extra}


# ───────────────────────── Regel ─────────────────────────

def test_ohne_einstellung_bekommt_jede_rechnung_eine_xrechnung():
    for cfg in ({}, {"xrechnung_karteitypen": [], "xrechnung_mindestbetrag": ""},
                {"xrechnung_karteitypen": None, "xrechnung_mindestbetrag": "0"}):
        assert xf.ausschlussgrund(_inv(typ=4, brutto="1.00"), cfg) is None


def test_karteityp_nicht_gewaehlt_keine_xrechnung():
    cfg = {"xrechnung_karteitypen": ["1", "2"]}                 # Firma und Reisebuero
    assert xf.ausschlussgrund(_inv(typ=1), cfg) is None
    assert xf.ausschlussgrund(_inv(typ=2.0), cfg) is None        # Oracle liefert NUMBER auch als float
    g = xf.ausschlussgrund(_inv(typ=4), cfg)
    assert g["regel"] == "karteityp" and g["karteityp"] == "4" and "Individuell" in g["text"]
    assert "Typ 9" in xf.ausschlussgrund(_inv(typ=9), cfg)["text"]


def test_unbekannter_karteityp_wird_nicht_ausgefiltert():
    """Fehlt der Typ (alter SQL-Override, leere Kartei), lieber XRechnung als still nur PDF."""
    cfg = {"xrechnung_karteitypen": ["1"]}
    assert xf.ausschlussgrund(_inv(typ=None), cfg) is None
    assert xf.ausschlussgrund({"header": {}, "totals": {}}, cfg) is None


def test_karteityp_der_rechnung_liest_die_kategorie_der_kartei():
    cur = MagicMock()
    cur.fetchone.return_value = (2,)
    assert xf.karteityp_der_rechnung(cur, 77) == "2"
    sql, binds = cur.execute.call_args[0]
    assert "xcca_internalcategory" in sql.lower() and binds == {"zinv_id": 77}
    cur.fetchone.return_value = None
    assert xf.karteityp_der_rechnung(cur, 77) is None
    cur.execute.side_effect = RuntimeError("ORA-00942")
    assert xf.karteityp_der_rechnung(cur, 77) is None


def test_mindestbetrag_strikt_kleiner_und_nur_rechnung_380():
    cfg = {"xrechnung_mindestbetrag": "250"}
    g = xf.ausschlussgrund(_inv(brutto="249.99"), cfg)
    assert g["regel"] == "mindestbetrag" and "249,99" in g["text"] and "250,00" in g["text"]
    assert xf.ausschlussgrund(_inv(brutto="250.00"), cfg) is None          # genau X bekommt eine
    assert xf.ausschlussgrund(_inv(brutto="100.00", code="381"), cfg) is None   # Gutschrift nie
    assert xf.ausschlussgrund(_inv(brutto="100.00", code="386"), cfg) is None   # nur 380


def test_mindestbetrag_erfasst_keine_null_und_negativen_betraege():
    """0,00 kann eine voll angezahlte Schlussrechnung sein, ein Minus eine Gutschrift."""
    cfg = {"xrechnung_mindestbetrag": "250"}
    for brutto in ("0.00", "-304.00", None, "abc"):
        assert xf.ausschlussgrund(_inv(brutto=brutto), cfg) is None


def test_mindestbetrag_mit_komma_und_unlesbarer_grenze():
    assert xf.ausschlussgrund(_inv(brutto="10.00"), {"xrechnung_mindestbetrag": "12,50"})["regel"] == "mindestbetrag"
    assert xf.ausschlussgrund(_inv(brutto="10.00"), {"xrechnung_mindestbetrag": "viel"}) is None


def test_mitgliedschaft_geht_vor():
    """Leitweg-ID/Kaeuferreferenz (DXR) oder Nur-XML: der Empfaenger will die XRechnung."""
    cfg = {"xrechnung_karteitypen": ["1"], "xrechnung_mindestbetrag": "250"}
    assert xf.ausschlussgrund(_inv(typ=4, brutto="10.00", kaeuferreferenz_mitglied=True), cfg) is None
    assert xf.ausschlussgrund(_inv(typ=4, brutto="10.00", xml_only="membership"), cfg) is None
    assert xf.ausschlussgrund(_inv(typ=4, brutto="10.00", xml_only="global"), cfg)["regel"] == "karteityp"


def test_karteityp_vor_mindestbetrag():
    cfg = {"xrechnung_karteitypen": ["1"], "xrechnung_mindestbetrag": "250"}
    assert xf.ausschlussgrund(_inv(typ=4, brutto="10.00"), cfg)["regel"] == "karteityp"


# ───────────────────────── Auswahl aus Suite8 ─────────────────────────

def test_karteitypen_auswahl_liest_vorhandene_typen():
    cur = MagicMock()
    # (Kategorie, Bezeichnung, inaktiv, Karteien) - aktive zuerst; zwei XCCA mit Kategorie 1
    cur.fetchall.return_value = [(1, "Firma", 0, 2500), (1, "Kreditkarte", 1, 15), (2, "Reisebüro/Agentur", 0, 800),
                                 (4, "Individuell", 0, 152048), (7, None, 0, 3), (None, "ohne", 0, 4)]
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock(cursor=MagicMock(return_value=cur)))
    cm.__exit__ = MagicMock(return_value=None)
    with patch.object(xf, "get_connection", return_value=cm):
        wahl = xf.karteitypen_auswahl()
    assert [w for w, _ in wahl] == ["1", "2", "4", "7"]
    assert wahl[0][1] == "Firma (2.515 Karteien)" and wahl[2][1] == "Individuell (152.048 Karteien)"
    assert wahl[3][1] == "Typ 7 (3 Karteien)"
    assert "select" in cur.execute.call_args[0][0].lower() and "xcca" in cur.execute.call_args[0][0].lower()


def test_karteitypen_auswahl_ohne_datenbank_leer():
    with patch.object(xf, "get_connection", side_effect=RuntimeError("keine DB")):
        assert xf.karteitypen_auswahl() == []


# ───────────────────────── Einstellungen ─────────────────────────

def _setting(key):
    return {x.key: x for sec in settings_schema.SECTIONS for x in sec.settings}[key]


def test_einstellung_karteitypen_mehrfachauswahl():
    s = _setting("xrechnung_karteitypen")
    assert s.type == "multi" and s.default == [] and s.file == "hotel.json" and s.choices_from
    assert settings_schema.coerce(s, ["2", 1, " 3 "]) == ["1", "2", "3"]
    assert settings_schema.coerce(s, []) == [] and settings_schema.coerce(s, None) == []
    with pytest.raises(settings_schema.SettingError):
        settings_schema.coerce(s, ["1; drop"])


def test_einstellung_mindestbetrag():
    s = _setting("xrechnung_mindestbetrag")
    assert settings_schema.coerce(s, "") == "" and settings_schema.coerce(s, "250") == "250.00"
    assert settings_schema.coerce(s, "12,5") == "12.50"
    for falsch in ("-1", "abc", "1.2.3"):
        with pytest.raises(settings_schema.SettingError):
            settings_schema.coerce(s, falsch)


def test_einstellungsseite_kann_mehrfachauswahl():
    html = (Path(__file__).resolve().parent.parent / "slim" / "frontend" / "settings.html").read_text(encoding="utf-8")
    assert '"multi"' in html and 'type="checkbox"' in html


# ───────────────────────── Poller ─────────────────────────

CFG = {"mail_strategy": "suite8", "suite8_recognize_filename_pattern": "",
       "suite8_recognize_subject_pattern": r"Rechnung Nr\.?\s*(?P<zinv_number>\d+)",
       "suite8_attachment_name_template": "{zinv_number}.xml"}


def _lauf(tmp_path, cfg, inv, frei=True):
    conn = MagicMock(name="conn")
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=None)
    poller._letzter_trigger_state = None
    with patch.object(poller, "load_hotel_config", return_value={**CFG, **cfg}), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "_read_trigger_state", return_value="aktiv"), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[{"wmai_id": 55, "filename": "x.pdf", "subject": "Rechnung Nr. 900001",
                                     "to": "gast@example.invalid"}]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number", return_value=9), \
         patch.object(poller.invoice_fetcher, "fetch_invoice", return_value=inv), \
         patch.object(poller.invoice_validator, "validate", return_value=[]) as val, \
         patch.object(poller.xml_builder, "build_and_validate", return_value=b"<Invoice/>"), \
         patch.object(poller.kosit_validator, "validate"), \
         patch.object(poller, "release_wmai", return_value=frei) as rel, \
         patch.object(poller, "attach_xml_to_wmai",
                      return_value={"wmaa_id": 1, "wtxt_id": 2}) as att:
        s = poller.run_once(data_dir=tmp_path)
    protokoll = [json.loads(z) for p in tmp_path.glob("audit-*.jsonl")
                 for z in p.read_text(encoding="utf-8").splitlines()]
    return s, rel, att, val, protokoll


def test_poller_gibt_ausgefilterte_mail_sofort_frei(tmp_path):
    s, rel, att, val, protokoll = _lauf(tmp_path, {"xrechnung_karteitypen": ["1"]}, _inv(typ=4))
    rel.assert_called_once()
    att.assert_not_called()
    val.assert_not_called()                      # fehlende Pflichtfelder halten eine Privatrechnung nicht auf
    assert s["ohne_xrechnung"] == 1 and s["attached"] == 0 and s["failed"] == 0
    e = [x for x in protokoll if x["event"] == "freigegeben_ohne_xrechnung"]
    assert len(e) == 1 and e[0]["wmai_id"] == 55 and e[0]["zinv_number"] == "900001"
    assert e[0]["details"]["regel"] == "karteityp" and "Individuell" in e[0]["details"]["grund"]


def test_poller_haengt_xrechnung_an_wenn_die_regel_nicht_greift(tmp_path):
    s, rel, att, _, _ = _lauf(tmp_path, {"xrechnung_karteitypen": ["1"], "xrechnung_mindestbetrag": "250"},
                              _inv(typ=1, brutto="500.00"))
    rel.assert_not_called()
    att.assert_called_once()
    assert s["attached"] == 1 and s.get("ohne_xrechnung", 0) == 0


def test_poller_protokolliert_nichts_wenn_die_mail_schon_frei_war(tmp_path):
    s, rel, att, _, protokoll = _lauf(tmp_path, {"xrechnung_mindestbetrag": "250"}, _inv(brutto="10.00"), frei=False)
    rel.assert_called_once()
    att.assert_not_called()
    assert s.get("ohne_xrechnung", 0) == 0
    assert not [x for x in protokoll if x["event"] == "freigegeben_ohne_xrechnung"]


def test_detailseite_zeigt_grund():
    html = (Path(__file__).resolve().parent.parent / "slim" / "frontend" / "rechnung.html").read_text(encoding="utf-8")
    assert "p.ausschluss" in html and "det.grund" in html
