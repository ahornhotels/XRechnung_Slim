"""Tests: Monatsbericht fuer die Abrechnung (Kanal TBH) - Zeitraum, Faelligkeit,
Zaehlung, Mail in der Suite8-Warteschlange, Einstellungen, API."""
import io
import json
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from slim.api_slim import abrechnung_api, auth_api
from slim.api_slim import status as status_api
from slim.core_slim import settings_schema
from slim.jobs_slim import abrechnung as ab

CFG = {"abrechnung_email": "abrechnung@dienstleister.example", "abrechnung_tag": 3,
       "absender_email": "hotel@haus.example",
       "suite8_recognize_subject_pattern": r"Rechnung\s+Nr\.?\s*(?P<zinv_number>\d+)"}


def _conn(zahlen=(12, 10), haus="Hotel Beispiel"):
    """Cursor, der je nach SQL antwortet und alle Aufrufe sammelt."""
    aufrufe = []
    cur = MagicMock()

    def execute(sql, binds=None):
        aufrufe.append((" ".join(sql.split()), binds))
        s = sql.lower()
        if "seq_wtxt" in s:
            cur.fetchone.return_value = (501,)
        elif "seq_wmai" in s:
            cur.fetchone.return_value = (9001,)
        elif "from wuss" in s:
            cur.fetchone.return_value = (haus if (binds or {}).get("n") == "Hotelid" else None,)
        elif "from wmai m" in s:
            cur.fetchone.return_value = zahlen
    cur.execute.side_effect = execute
    conn = MagicMock(name="conn", cursor=MagicMock(return_value=cur))
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=None)
    return cm, conn, aufrufe


# ───────────────────────── Zeitraum und Faelligkeit ─────────────────────────

def test_letzter_monat_auch_ueber_den_jahreswechsel():
    assert ab.letzter_monat(date(2026, 11, 27)) == (date(2026, 10, 1), date(2026, 11, 1))
    assert ab.letzter_monat(date(2027, 1, 1)) == (date(2026, 12, 1), date(2027, 1, 1))
    assert ab.letzter_monat(date(2028, 3, 31)) == (date(2028, 2, 1), date(2028, 3, 1))
    assert ab.monat_von("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))
    for falsch in ("2026-13", "26-10", "", None):
        with pytest.raises(ab.AbrechnungFehler):
            ab.monat_von(falsch)


def test_faellig_ab_dem_eingestellten_tag_und_nur_einmal():
    leer = {"gesendet": {}}
    assert ab.faellig(CFG, date(2026, 11, 2), leer) is None            # vor dem Tag
    assert ab.faellig(CFG, date(2026, 11, 3), leer) == "2026-10"       # am Tag
    assert ab.faellig(CFG, date(2026, 11, 20), leer) == "2026-10"      # Dienst lief am Tag nicht: nachholen
    assert ab.faellig(CFG, date(2026, 11, 20), {"gesendet": {"2026-10": {}}}) is None
    assert ab.faellig(CFG, date(2026, 12, 3), {"gesendet": {"2026-10": {}}}) == "2026-11"


def test_ohne_empfaenger_aus_und_tag_begrenzt():
    assert ab.faellig({**CFG, "abrechnung_email": ""}, date(2026, 11, 20), {"gesendet": {}}) is None
    assert ab._tag({"abrechnung_tag": 31}) == 28 and ab._tag({"abrechnung_tag": 0}) == 1
    assert ab._tag({}) == 1 and ab._tag({"abrechnung_tag": "x"}) == 1


# ───────────────────────── Zaehlen und Text ─────────────────────────

def test_zaehlen_nimmt_mails_mit_xml_im_zeitraum():
    _, conn, aufrufe = _conn((12, 10))
    assert ab.zaehlen(conn, date(2026, 10, 1), date(2026, 11, 1)) == {"erstellt": 12, "versendet": 10}
    sql, binds = aufrufe[0]
    assert sql.lower().startswith("select") and "wmaa" in sql.lower() and "'%.xml'" in sql.lower()
    assert "wmai_fideliodate >= :von" in sql.lower() and "wmai_fideliodate < :bis" in sql.lower()
    assert binds == {"von": date(2026, 10, 1), "bis": date(2026, 11, 1)}


def test_berichtstext_nennt_betrieb_zeitraum_und_zahlen():
    betreff, text = ab.berichtstext("Hotel Beispiel", date(2026, 10, 1), date(2026, 11, 1),
                                    {"erstellt": 12, "versendet": 10}, "2.4.14-tbh", date(2026, 11, 3))
    assert betreff == "Slim Monatsbericht 10/2026 Hotel Beispiel"
    for teil in ("Betrieb:  Hotel Beispiel", "Zeitraum: 01.10.2026 bis 31.10.2026",
                 "Erstellte XRechnungen:   12", "Versendete XRechnungen:  10", "2.4.14-tbh", "03.11.2026"):
        assert teil in text
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    # Der Betreff darf keine Sperre fuer Rechnungsmails ausloesen
    assert "rechnung" not in betreff.lower() and "invoice" not in betreff.lower() and "#" not in betreff


def test_mailtext_liegt_wie_in_suite8():
    blob = ab._mailtext_blob("Grüße\r\nZeile 2")
    z = zipfile.ZipFile(io.BytesIO(blob))
    assert z.namelist() == ["stream"] and z.infolist()[0].compress_type == zipfile.ZIP_DEFLATED
    assert z.read("stream") == "Grüße\r\nZeile 2".encode("cp1252")


# ───────────────────────── Senden ─────────────────────────

def test_senden_legt_textmail_in_die_warteschlange(tmp_path):
    cm, conn, aufrufe = _conn((12, 10))
    with patch.object(ab, "get_connection", return_value=cm):
        r = ab.senden(tmp_path, CFG, date(2026, 11, 3))
    assert r["monat"] == "2026-10" and r["erstellt"] == 12 and r["versendet"] == 10 and r["wmai_id"] == 9001
    wtxt = next(b for s, b in aufrufe if s.startswith("INSERT INTO WTXT"))
    assert wtxt["id"] == 501 and wtxt["blob_size"] == len(wtxt["blob_data"])
    assert "Erstellte XRechnungen:   12" in zipfile.ZipFile(io.BytesIO(wtxt["blob_data"])).read("stream").decode("cp1252")
    sql, wmai = next((s, b) for s, b in aufrufe if s.startswith("INSERT INTO WMAI"))
    assert wmai == {"id": 9001, "body": 501, "sender": "hotel@haus.example",
                    "empf": "abrechnung@dienstleister.example",
                    "betreff": "Slim Monatsbericht 10/2026 Hotel Beispiel"}
    assert "WMAI_BLOCKSEND" in sql and ", 0, 0, :sender, :empf, :betreff, 0, 0, 0, 0)" in sql   # nicht gesperrt
    conn.commit.assert_called_once()
    stand = json.loads((tmp_path / "abrechnung.json").read_text(encoding="utf-8"))
    assert stand["gesendet"]["2026-10"]["erstellt"] == 12 and stand["gesendet"]["2026-10"]["an"] == CFG["abrechnung_email"]
    protokoll = [json.loads(z) for p in tmp_path.glob("audit-*.jsonl") for z in p.read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in protokoll] == ["abrechnung_gesendet"] and protokoll[0]["details"]["monat"] == "2026-10"


def test_senden_rollt_bei_fehler_zurueck_und_merkt_nichts(tmp_path):
    cm, conn, _ = _conn()
    alt = conn.cursor.return_value.execute.side_effect

    def kaputt(sql, binds=None):
        if sql.lstrip().upper().startswith("INSERT INTO WMAI"):
            raise RuntimeError("ORA-01031")
        return alt(sql, binds)
    conn.cursor.return_value.execute.side_effect = kaputt
    with patch.object(ab, "get_connection", return_value=cm), pytest.raises(RuntimeError):
        ab.senden(tmp_path, CFG, date(2026, 11, 3))
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    assert not (tmp_path / "abrechnung.json").exists()


def test_senden_verweigert_ohne_empfaenger_absender_oder_fuer_laufenden_monat(tmp_path):
    cm, conn, aufrufe = _conn()
    with patch.object(ab, "get_connection", return_value=cm):
        with pytest.raises(ab.AbrechnungFehler, match="Empfänger"):
            ab.senden(tmp_path, {**CFG, "abrechnung_email": "kein-at"}, date(2026, 11, 3))
        with pytest.raises(ab.AbrechnungFehler, match="abgelaufene"):
            ab.senden(tmp_path, CFG, date(2026, 11, 3), monat="2026-11")
        with pytest.raises(ab.AbrechnungFehler, match="Absender"):
            ab.senden(tmp_path, {**CFG, "absender_email": ""}, date(2026, 11, 3))
    assert not [s for s, _ in aufrufe if s.startswith("INSERT")]


def test_senden_verweigert_wenn_der_betreff_als_rechnungsmail_gilt(tmp_path):
    cm, _, aufrufe = _conn()
    cfg = {**CFG, "suite8_recognize_subject_pattern": r"Monatsbericht (?P<zinv_number>\d+)"}
    with patch.object(ab, "get_connection", return_value=cm), pytest.raises(ab.AbrechnungFehler, match="gesperrt"):
        ab.senden(tmp_path, cfg, date(2026, 11, 3))
    assert not [s for s, _ in aufrufe if s.startswith("INSERT")]


def test_absender_faellt_auf_suite8_zurueck():
    _, conn, _ = _conn()
    conn.cursor.return_value.execute.side_effect = None
    conn.cursor.return_value.fetchone.return_value = ("empfang@haus.example",)
    assert ab.absender(conn, {}) == "empfang@haus.example"
    assert ab.absender(conn, {"seller_contact_email": "buchhaltung@haus.example"}) == "buchhaltung@haus.example"


def test_zeitlauf_sendet_einmal_und_protokolliert_fehler(tmp_path):
    cm, _, aufrufe = _conn()
    with patch.object(ab, "get_connection", return_value=cm), patch.object(ab, "load_hotel_config", return_value=CFG):
        assert ab.run_once(tmp_path, date(2026, 11, 2)) == {"gesendet": False}
        assert ab.run_once(tmp_path, date(2026, 11, 3))["gesendet"] is True
        assert ab.run_once(tmp_path, date(2026, 11, 4)) == {"gesendet": False}
    assert len([s for s, _ in aufrufe if s.startswith("INSERT INTO WMAI")]) == 1
    with patch.object(ab, "get_connection", side_effect=RuntimeError("keine DB")), \
         patch.object(ab, "load_hotel_config", return_value=CFG):
        r = ab.run_once(tmp_path, date(2026, 12, 5))
    assert r["gesendet"] is False and "keine DB" in r["fehler"]
    assert "2026-11" not in ab.stand_lesen(tmp_path)["gesendet"]      # naechster Lauf versucht es wieder


# ───────────────────────── Einstellungen, API, Einbindung ─────────────────────────

def test_einstellungen_abrechnung():
    sec = settings_schema.section("abrechnung")
    assert sec.page == "system" and [s.key for s in sec.settings] == ["abrechnung_email", "abrechnung_tag"]
    tag = sec.settings[1]
    assert tag.type == "int" and tag.minimum == 1 and tag.maximum == 28 and tag.default == 1
    with pytest.raises(settings_schema.SettingError):
        settings_schema.coerce(sec.settings[0], "kein-at")
    with pytest.raises(settings_schema.SettingError):
        settings_schema.coerce(tag, "29")


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(abrechnung_api.router)
    status_api.get_state().update({"data_dir": tmp_path})
    return TestClient(app), tmp_path


def test_api_vorschau_und_versand_von_hand(client):
    c, dd = client
    cm, _, aufrufe = _conn((7, 6))
    with patch.object(ab, "get_connection", return_value=cm), \
         patch.object(abrechnung_api, "load_hotel_config", return_value=CFG), \
         patch.object(abrechnung_api, "now_local", return_value=MagicMock(date=lambda: date(2026, 11, 27))), \
         patch.object(ab, "now_local", return_value=MagicMock(date=lambda: date(2026, 11, 27),
                                                              isoformat=lambda: "2026-11-27T10:00:00+01:00")):
        g = c.get("/api/abrechnung").json()
        assert g["aktiv"] is True and g["tag"] == 3 and g["gesendet"] == {}
        assert g["vorschau"]["monat"] == "2026-10" and g["vorschau"]["erstellt"] == 7 and g["vorschau"]["versendet"] == 6
        assert not [s for s, _ in aufrufe if s.startswith("INSERT")]          # Vorschau schreibt nicht
        p = c.post("/api/abrechnung/senden", json={})
        assert p.status_code == 200 and p.json()["monat"] == "2026-10" and p.json()["von_hand"]
        assert c.post("/api/abrechnung/senden", json={"monat": "2026-11"}).status_code == 409
        assert "2026-10" in c.get("/api/abrechnung").json()["gesendet"]


def test_api_ohne_datenbank(client):
    c, _ = client
    with patch.object(ab, "get_connection", side_effect=RuntimeError("ORA-12541 geheim")), \
         patch.object(abrechnung_api, "load_hotel_config", return_value=CFG):
        g = c.get("/api/abrechnung").json()
        assert g["vorschau"] is None and "ORA-" not in g["fehler"]
        p = c.post("/api/abrechnung/senden", json={})
        assert p.status_code == 503 and "ORA-" not in p.json()["detail"]


def test_abrechnung_nur_fuer_verwalter_und_im_dienst_eingebunden():
    assert auth_api._needs_admin("GET", "/api/abrechnung") is True
    assert auth_api._needs_admin("POST", "/api/abrechnung/senden") is True
    root = Path(__file__).resolve().parent.parent
    main = (root / "slim" / "main_slim.py").read_text(encoding="utf-8")
    assert "abrechnung_api_module.router" in main and "slim_abrechnung" in main
    html = (root / "slim" / "frontend" / "settings.html").read_text(encoding="utf-8")
    assert "/api/abrechnung" in html and 'id="abrechnung-card"' in html
