"""Tests: Einstellungs-Teil des Handbuchs (GET /api/handbuch/einstellungen)."""
import json

from slim.api_slim import auth_api, settings_api
from slim.core_slim import settings_schema as schema


def test_liefert_alle_abschnitte_und_felder():
    j = settings_api.handbuch_einstellungen()
    assert [s["id"] for s in j["sections"]] == [s.id for s in schema.SECTIONS]
    keys = [f["key"] for s in j["sections"] for f in s["fields"]]
    assert keys == [x.key for s in schema.SECTIONS for x in s.settings]
    seiten = {s["page"] for s in j["sections"]}
    assert seiten == {"xrechnung", "hotel", "system"}


def test_nur_beschreibung_und_standard_keine_werte():
    j = settings_api.handbuch_einstellungen()
    for s in j["sections"]:
        for f in s["fields"]:
            assert "value" not in f and "gesetzt" not in f
            assert {"label", "help", "default", "restart", "info"} <= set(f)
    f = {f["key"]: f for s in j["sections"] for f in s["fields"]}
    assert f["password"]["default"] is None and f["pat_token"]["default"] is None
    assert f["rundungsausgleich"]["default"] == "abschlag"
    assert f["rundungsausgleich"]["choices"] == ["aus", "position", "abschlag"]
    assert f["rundungsausgleich"]["info"]


def test_liest_keine_konfigdateien(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("darf keine Datei lesen")
    monkeypatch.setattr(settings_api, "_load", boom)
    json.dumps(settings_api.handbuch_einstellungen())


def test_fuer_alle_angemeldeten_lesbar():
    assert not auth_api._needs_admin("GET", "/api/handbuch/einstellungen")


def test_handbuch_hat_konfigteil():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "slim" / "frontend" / "handbuch.html").read_text(encoding="utf-8")
    for txt in ("/api/handbuch/einstellungen", 'id="einstellungen"', "Muster-Assistent",
                "Für Techniker / DBA", "Verkäuferdaten", "Benutzer", "Standard", r"slim\reset_admin.cmd"):
        assert txt in src, txt


def test_handbuch_hat_xrechnung_grundlagen():
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "slim" / "frontend" / "handbuch.html").read_text(encoding="utf-8")
    for txt in ('id="xrechnung"', "EN 16931", "KoSIT", "Leitweg-ID", "BT-10", "BT-49", "BR-DE",
                "UBL", "3.0.2", "1.1.2027", "Kleinbetragsrechnung", "Wird von der Konfiguration abgedeckt"):
        assert txt in src, txt
    nummern = [int(n) for n in re.findall(r"<h2>(\d+)\. ", src)]
    assert nummern == list(range(1, len(nummern) + 1))
