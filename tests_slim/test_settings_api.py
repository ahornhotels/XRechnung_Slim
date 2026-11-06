"""Tests: Einstellungen in der Oberflaeche (Schema, Lesen, Schreiben)."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from slim.api_slim import settings_api
from slim.core_slim import settings_schema


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "hotel.json").write_text(json.dumps({"hotel_code": "XYZ", "eigener_schluessel": 1}), encoding="utf-8")
    (cfg / "app_settings.json").write_text(json.dumps({"port": 8022, "host": "127.0.0.1"}), encoding="utf-8")
    (cfg / "connection.json").write_text(json.dumps({"tns_alias": "V8", "password": "gAAAA-alt"}), encoding="utf-8")
    monkeypatch.setattr(settings_api, "CONFIG_DIR", cfg)
    monkeypatch.setattr(settings_api, "DATA_DIR", tmp_path)
    app = FastAPI()
    app.include_router(settings_api.router)
    app.include_router(settings_api.system_router)
    return TestClient(app), cfg, tmp_path


def _field(data, section, key):
    sec = next(s for s in data["sections"] if s["id"] == section)
    return next(f for f in sec["fields"] if f["key"] == key)


def test_jede_einstellung_hat_erklaertext():
    for sec in settings_schema.SECTIONS:
        for s in sec.settings:
            assert s.help.strip() and s.label.strip(), s.key


def test_geheimnisse_werden_nie_zurueckgegeben(env):
    client, _, _ = env
    data = client.get("/api/settings").json()
    pw = _field(data, "datenbank", "password")
    assert pw["gesetzt"] is True and "value" not in pw
    assert "gAAAA-alt" not in json.dumps(data)


def test_werte_und_standard(env):
    client, _, _ = env
    data = client.get("/api/settings").json()
    assert _field(data, "hotel", "hotel_code")["value"] == "XYZ"
    assert _field(data, "inhalt", "positionen_zusammenfassen")["value"] is True     # Standard
    assert _field(data, "server", "port")["restart"] is True


def test_speichern_sicherung_und_fremde_schluessel_bleiben(env):
    client, cfg, _ = env
    r = client.put("/api/settings/hotel", json={"values": {"hotel_code": "ABC", "default_payment_terms_days": "30"}})
    assert r.status_code == 200
    saved = json.loads((cfg / "hotel.json").read_text(encoding="utf-8"))
    assert saved["hotel_code"] == "ABC" and saved["default_payment_terms_days"] == 30
    assert saved["eigener_schluessel"] == 1
    assert list(cfg.glob("hotel.json.*.sicherung"))


def test_leeres_geheimnis_bleibt_unveraendert(env):
    client, cfg, _ = env
    r = client.put("/api/settings/datenbank", json={"values": {"tns_alias": "V8", "password": ""}})
    assert r.status_code == 200
    saved = json.loads((cfg / "connection.json").read_text(encoding="utf-8"))
    assert saved["password"] == "gAAAA-alt" and saved["tns_alias"] == "V8"


def test_neues_geheimnis_wird_verschluesselt(env):
    client, cfg, _ = env
    client.put("/api/settings/datenbank", json={"values": {"password": "neues-db-passwort"}})
    raw = (cfg / "connection.json").read_text(encoding="utf-8")
    assert "neues-db-passwort" not in raw
    from core.crypto import decrypt, load_key
    assert decrypt(json.loads(raw)["password"], load_key(cfg / "connection.key")) == "neues-db-passwort"


def test_ungueltige_eingabe_422_ohne_aenderung(env):
    client, cfg, _ = env
    before = (cfg / "app_settings.json").read_text(encoding="utf-8")
    r = client.put("/api/settings/server", json={"values": {"port": "abc", "allowed_ips": "10.0.0.0/8, kein-netz"}})
    assert r.status_code == 422
    errs = r.json()["detail"]
    assert {"port", "allowed_ips"} <= set(errs)
    assert (cfg / "app_settings.json").read_text(encoding="utf-8") == before
    assert not list(cfg.glob("app_settings.json.*.sicherung"))


def test_unbekannter_schluessel_abgelehnt(env):
    client, _, _ = env
    r = client.put("/api/settings/hotel", json={"values": {"port": 1}})
    assert r.status_code == 422


def test_audit_ohne_werte(env):
    client, _, data_dir = env
    client.put("/api/settings/datenbank", json={"values": {"password": "streng-geheim-123"}})
    text = "".join(p.read_text(encoding="utf-8") for p in data_dir.glob("audit-*.jsonl"))
    assert "settings_changed" in text and "password" in text and "streng-geheim-123" not in text


def test_gastzeile_mit_unbekanntem_platzhalter(env):
    client, _, _ = env
    r = client.put("/api/settings/inhalt", json={"values": {"gastzeile": "Gast: {name}"}})
    assert r.status_code == 422 and "gastzeile" in r.json()["detail"]


def test_neustart_ruft_dienst_neustart(env, monkeypatch):
    client, _, _ = env
    called = []
    monkeypatch.setattr(settings_api, "_restart_service", lambda: called.append(1))
    assert client.post("/api/system/restart").status_code == 200 and called == [1]


# --- Verkaeuferdaten (Task 5) ---

def test_verkaeufer_suite8_wert_und_abweichung(env, monkeypatch):
    client, cfg, _ = env
    monkeypatch.setattr(settings_api, "_suite8_seller_values", lambda: {"suppliername": "Hotel aus Suite8"})
    data = client.get("/api/settings/seller").json()
    row = next(r for r in data if r["key"] == "suppliername")
    assert row["suite8"] == "Hotel aus Suite8" and row["abweichend"] == ""
    assert client.put("/api/settings/seller", json={"values": {"suppliername": "Hotel GmbH", "suppliercityname": ""}}).status_code == 200
    saved = json.loads((cfg / "hotel.json").read_text(encoding="utf-8"))
    assert saved["seller_overrides"] == {"suppliername": "Hotel GmbH"}


def test_verkaeufer_unbekanntes_feld_abgelehnt(env):
    client, _, _ = env
    assert client.put("/api/settings/seller", json={"values": {"customername": "x"}}).status_code == 422


def test_fetcher_wendet_verkaeufer_override_an(monkeypatch):
    from modules import invoice_fetcher
    monkeypatch.setattr(invoice_fetcher, "load_json",
                        lambda p, default=None: {"seller_overrides": {"suppliername": "Hotel GmbH", "suppliercityname": " "}})
    h = {"suppliername": "Suite8-Name", "suppliercityname": "Musterstadt"}
    invoice_fetcher._apply_seller_overrides(h)
    assert h == {"suppliername": "Hotel GmbH", "suppliercityname": "Musterstadt"}


# --- Security-Review Einstellungen ---

def test_neues_db_ziel_verlangt_passwort(env):
    client, cfg, _ = env
    r = client.put("/api/settings/datenbank", json={"values": {"tns_alias": "FREMD"}})
    assert r.status_code == 422 and "password" in r.json()["detail"]
    assert json.loads((cfg / "connection.json").read_text(encoding="utf-8"))["tns_alias"] == "V8"
    r = client.put("/api/settings/datenbank", json={"values": {"tns_alias": "FREMD", "password": "neues-db-passwort"}})
    assert r.status_code == 200


def test_unveraendertes_db_ziel_braucht_kein_passwort(env):
    client, _, _ = env
    assert client.put("/api/settings/datenbank", json={"values": {"tns_alias": "V8"}}).status_code == 200


@pytest.mark.parametrize("key,value", [("owner", "../evil"), ("repo", "a/b"), ("owner", "x" * 101)])
def test_update_quelle_streng_geprueft(env, key, value):
    client, _, _ = env
    assert client.put("/api/settings/update", json={"values": {key: value}}).status_code == 422


@pytest.mark.parametrize("value", [r"\server\share\client", "relativ\pfad", "//server/share"])
def test_client_pfade_nur_lokal_absolut(env, value):
    client, _, _ = env
    r = client.put("/api/settings/datenbank",
                   json={"values": {"oracle_client_lib_dir": value, "password": "neues-db-passwort"}})
    assert r.status_code == 422 and "oracle_client_lib_dir" in r.json()["detail"]


def test_leerer_client_pfad_erlaubt(env):
    client, _, _ = env
    r = client.put("/api/settings/datenbank", json={"values": {"oracle_client_lib_dir": "", "password": "neues-db-passwort"}})
    assert r.status_code == 200



# --- Review zur Einstellungs-API ---

def test_versand_braucht_ein_erkennungsmuster(env):
    client, _, _ = env
    r = client.put("/api/settings/versand", json={"values": {
        "suite8_recognize_subject_pattern": "", "suite8_recognize_filename_pattern": ""}})
    assert r.status_code == 422 and "suite8_recognize_subject_pattern" in r.json()["detail"]


def test_betreffmuster_standard_sichtbar_und_nicht_geleert(env):
    client, cfg, _ = env
    data = client.get("/api/settings").json()
    assert "zinv_number" in _field(data, "versand", "suite8_recognize_subject_pattern")["value"]
    assert client.put("/api/settings/versand", json={"values": {"absender_email": "rechnung@example.com"}}).status_code == 200
    assert "suite8_recognize_subject_pattern" not in json.loads((cfg / "hotel.json").read_text(encoding="utf-8"))


def test_muster_mit_zwei_gruppen_abgelehnt(env):
    client, _, _ = env
    r = client.put("/api/settings/versand", json={"values": {
        "suite8_recognize_subject_pattern": r"(?P<zinv_id>\d+)-(?P<zinv_number>\d+)"}})
    assert r.status_code == 422


def test_sicherungen_begrenzt(env, monkeypatch):
    client, cfg, _ = env
    monkeypatch.setattr(settings_api, "_KEEP_BACKUPS", 3)
    for i in range(6):
        client.put("/api/settings/hotel", json={"values": {"hotel_code": f"H{i}"}})
    assert len(list(cfg.glob("hotel.json.*.sicherung"))) == 3


def test_verkaeufer_rechtlicher_name_und_iban(env, monkeypatch):
    client, cfg, _ = env
    monkeypatch.setattr(settings_api, "_suite8_seller_values", lambda: {})
    keys = [r["key"] for r in client.get("/api/settings/seller").json()]
    assert "supplierregistrationname" in keys
    client.put("/api/settings/seller", json={"values": {"payeefinancialaccountid": "DE89 3704 0044 0532 0130 00"}})
    saved = json.loads((cfg / "hotel.json").read_text(encoding="utf-8"))
    assert saved["seller_overrides"]["payeefinancialaccountid"] == "DE89370400440532013000"


def test_fetcher_override_rechtlicher_name(monkeypatch):
    from modules import invoice_fetcher
    monkeypatch.setattr(invoice_fetcher, "load_json",
                        lambda p, default=None: {"seller_overrides": {"supplierregistrationname": "Hotel GmbH"}})
    h = {"supplierregistrationname": "Alt"}
    invoice_fetcher._apply_seller_overrides(h)
    assert h["supplierregistrationname"] == "Hotel GmbH"


def test_save_json_atomar(tmp_path):
    from core.config_loader import save_json
    p = tmp_path / "x.json"
    save_json(p, {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    assert not list(tmp_path.glob("*.tmp"))



# --- letztes Review ---

def test_tnsnames_auf_netzlaufwerk_erlaubt(env):
    client, _, _ = env
    r = client.put("/api/settings/datenbank",
                   json={"values": {"tns_admin": r"\\fidelio\oracle\network\admin", "password": "neues-db-passwort"}})
    assert r.status_code == 200


def test_unveraenderter_altwert_blockiert_speichern_nicht(env):
    client, cfg, _ = env
    (cfg / "connection.json").write_text(json.dumps({"tns_alias": "V8 ", "tns_admin": None,
        "oracle_client_lib_dir": "relativ", "password": "gAAAA-alt"}), encoding="utf-8")
    r = client.put("/api/settings/datenbank", json={"values": {
        "tns_alias": "V8", "tns_admin": "", "oracle_client_lib_dir": "relativ", "username": ""}})
    assert r.status_code == 200, r.text


def test_atomares_schreiben_versucht_erneut_bei_windows_sperre(tmp_path, monkeypatch):
    import os as _os
    from core import config_loader
    real = _os.replace
    tries = []

    def flaky(src, dst):
        tries.append(1)
        if len(tries) < 3:
            raise PermissionError("[WinError 32] in Benutzung")
        return real(src, dst)
    monkeypatch.setattr(_os, "replace", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    config_loader.atomic_write_json(tmp_path / "a.json", {"x": 1})
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8")) == {"x": 1}
    assert len(tries) == 3 and not list(tmp_path.glob("*.tmp"))
