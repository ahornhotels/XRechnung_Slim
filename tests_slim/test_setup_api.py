"""Tests fuer slim/api_slim/setup_api — Setup-Wizard-Endpoints.

DB-abhaengige Endpoints (db/test, wuss/standard, wuss/udef) werden
gegen einen gemockten oracledb-Pool getestet.
"""
import importlib
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Isoliertes SUITE8_CONFIG_DIR und ein hotel.json mit Minimaldaten."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    monkeypatch.setenv("SUITE8_CONFIG_DIR", str(cfg_dir))

    import core.config_loader as cl
    importlib.reload(cl)
    from slim.api_slim import setup_api
    importlib.reload(setup_api)

    app = FastAPI()
    app.include_router(setup_api.router)
    return TestClient(app), cfg_dir, setup_api


def _setup_done(cfg_dir):
    (cfg_dir / ".setup_done").write_text("done", encoding="utf-8")


def test_status_initial(client):
    c, _, _ = client
    j = c.get("/api/setup/status").json()
    assert j["setup_done"] is False
    assert j["has_db_config"] is False
    assert j["has_hotel"] is False


def test_status_when_done(client):
    c, cfg, _ = client
    _setup_done(cfg)
    j = c.get("/api/setup/status").json()
    assert j["setup_done"] is True


def test_db_test_blocked_when_setup_done(client):
    c, cfg, _ = client
    _setup_done(cfg)
    r = c.post("/api/setup/db/test", json={
        "tns_alias": "V8", "username": "u", "password": "p",
    })
    assert r.status_code == 403


def test_db_test_persists_and_reports_success(client):
    c, cfg, setup_api = client
    fake_info = {"db_name": "V8LIVE", "user": "V8Live"}
    with patch.object(setup_api, "db_connector") as dbc:
        dbc._pool = None
        dbc.test_connection.return_value = fake_info
        r = c.post("/api/setup/db/test", json={
            "tns_alias": "V8", "username": "V8Live", "password": "geheim",
            "tns_admin": "/path", "oracle_client_lib_dir": "",
        })
    j = r.json()
    assert j["ok"] is True and j["user"] == "V8Live"
    # connection.json wurde geschrieben mit verschluesseltem Passwort
    conn = json.loads((cfg / "connection.json").read_text(encoding="utf-8"))
    assert conn["username"] == "V8Live"
    assert conn["password"] != "geheim"  # encrypted


def test_db_test_reports_failure(client):
    c, _, setup_api = client
    with patch.object(setup_api, "db_connector") as dbc:
        dbc._pool = None
        dbc.test_connection.side_effect = RuntimeError("ORA-12154")
        r = c.post("/api/setup/db/test", json={
            "tns_alias": "BAD", "username": "u", "password": "p",
        })
    j = r.json()
    assert j["ok"] is False and "ORA-12154" in j["error"]


def test_wuss_standard_reports_missing(client):
    c, _, setup_api = client
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    # 4 vorhanden, 8 fehlen (None oder leer)
    responses = [("TST",), ("Testhotel",), ("Teststrasse 1",), ("Teststadt",),
                 (None,), (None,), (None,), (None,),
                 (None,), (None,), (None,), (None,)]
    fake_cur.fetchone.side_effect = responses
    fake_conn.cursor.return_value = fake_cur
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=fake_conn)
    cm.__exit__ = MagicMock(return_value=None)
    with patch.object(setup_api.db_connector, "get_connection", return_value=cm):
        j = c.get("/api/setup/wuss/standard").json()
    assert j["missing_count"] == 8
    assert len(j["items"]) == 12


def test_wuss_udef_inserts_missing(client):
    c, _, setup_api = client
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    # Pro UDEF-Key: 1x SELECT wuss_value (existence-check in /udef GET),
    # dann 1x SELECT 1 FROM wuss in POST/insert path.
    # Wir test nur POST hier - der ruft SELECT 1 fuer existence.
    # ALLE drei UDEFs fehlen -> SELECT liefert None
    fake_cur.fetchone.return_value = None
    fake_conn.cursor.return_value = fake_cur
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=fake_conn)
    cm.__exit__ = MagicMock(return_value=None)

    with patch.object(setup_api.db_connector, "get_connection", return_value=cm):
        r = c.post("/api/setup/wuss/udef", json={"values": {
            "UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE": "14",
            "UDEF_XRECHNUNG_RESPONSIBLE_NAME": "Buchhaltung",
        }})
    j = r.json()
    assert set(j["inserted"]) == {
        "UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE",
        "UDEF_XRECHNUNG_RESPONSIBLE_NAME",
    }
    assert j["blocked"] == []


def test_wuss_udef_skips_existing(client):
    c, _, setup_api = client
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = (1,)  # SELECT 1 → existiert
    fake_conn.cursor.return_value = fake_cur
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=fake_conn)
    cm.__exit__ = MagicMock(return_value=None)

    with patch.object(setup_api.db_connector, "get_connection", return_value=cm):
        r = c.post("/api/setup/wuss/udef", json={"values": {
            "UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE": "14",
        }})
    assert r.json()["skipped_existing"] == ["UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE"]


def test_wuss_udef_ignores_unknown_keys(client):
    c, _, setup_api = client
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = None
    fake_conn.cursor.return_value = fake_cur
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=fake_conn)
    cm.__exit__ = MagicMock(return_value=None)
    with patch.object(setup_api.db_connector, "get_connection", return_value=cm):
        r = c.post("/api/setup/wuss/udef", json={"values": {
            "EVIL_KEY": "boom",
            "UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE": "14",
        }})
    j = r.json()
    assert j["inserted"] == ["UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE"]
    # EVIL_KEY wird stillschweigend ignoriert (kein blocked-Eintrag,
    # kein insert)


def test_trigger_sql_uses_filename_pattern_when_set(client):
    c, cfg, _ = client
    (cfg / "hotel.json").write_text(json.dumps({
        "suite8_recognize_filename_pattern": r"Folio.*\.pdf$",
        "suite8_recognize_subject_pattern": "",
    }), encoding="utf-8")
    j = c.get("/api/setup/trigger-sql").json()
    assert "WMAI_ATTACHMENT_FILE_NAME" in j["sql"]
    assert "WMAI_SUBJECT" not in j["sql"]


def test_trigger_sql_uses_subject_pattern_when_set(client):
    c, cfg, _ = client
    (cfg / "hotel.json").write_text(json.dumps({
        "suite8_recognize_filename_pattern": "",
        "suite8_recognize_subject_pattern":
            r"Rechnung Nr\.?\s*(?P<zinv_number>\d+)",
    }), encoding="utf-8")
    j = c.get("/api/setup/trigger-sql").json()
    assert "WMAI_SUBJECT" in j["sql"]


def test_pattern_save_persists(client):
    c, cfg, _ = client
    (cfg / "hotel.json").write_text("{}", encoding="utf-8")
    r = c.post("/api/setup/pattern", json={
        "subject_pattern": r"Invoice (?P<zinv_number>\d+)",
        "filename_pattern": "",
        "attachment_name_template": "{zinv_number}.xml",
    })
    assert r.status_code == 200
    saved = json.loads((cfg / "hotel.json").read_text(encoding="utf-8"))
    assert "zinv_number" in saved["suite8_recognize_subject_pattern"]


def test_hotel_save_persists_and_keeps_pattern(client):
    c, cfg, _ = client
    (cfg / "hotel.json").write_text(json.dumps({
        "suite8_recognize_subject_pattern": r"X(?P<zinv_number>\d+)",
    }), encoding="utf-8")
    r = c.post("/api/setup/hotel", json={
        "hotel_code": "TST",
        "hotel_long_name": "Testhotel",
        "absender_email": "x@y.z",
        "default_payment_terms_days": 14,
        "currency": "EUR",
        "seller_contact_name": "Buchhaltung",
    })
    assert r.status_code == 200
    saved = json.loads((cfg / "hotel.json").read_text(encoding="utf-8"))
    assert saved["hotel_code"] == "TST"
    # Pattern blieb erhalten
    assert "zinv_number" in saved["suite8_recognize_subject_pattern"]


def test_finish_blocked_without_password(client):
    c, cfg, _ = client
    (cfg / "hotel.json").write_text(json.dumps({"hotel_code": "X"}), encoding="utf-8")
    (cfg / "connection.json").write_text("{}", encoding="utf-8")
    r = c.post("/api/setup/finish")
    assert r.status_code == 400
    assert "Oracle" in r.json()["detail"]


def test_finish_blocked_without_pattern(client):
    c, cfg, _ = client
    (cfg / "hotel.json").write_text(json.dumps({"hotel_code": "X"}), encoding="utf-8")
    (cfg / "connection.json").write_text(json.dumps({
        "password": "gAAAA..."
    }), encoding="utf-8")
    r = c.post("/api/setup/finish")
    assert r.status_code == 400
    assert "Pattern" in r.json()["detail"]


def test_finish_writes_marker_and_attempts_service(client):
    c, cfg, setup_api = client
    (cfg / "hotel.json").write_text(json.dumps({
        "hotel_code": "X",
        "suite8_recognize_subject_pattern": r"Y(?P<zinv_number>\d+)",
    }), encoding="utf-8")
    (cfg / "connection.json").write_text(json.dumps({
        "password": "gAAAA..."
    }), encoding="utf-8")

    fake_proc = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch.object(setup_api.subprocess, "run", return_value=fake_proc):
        r = c.post("/api/setup/finish")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert (cfg / ".setup_done").exists()
