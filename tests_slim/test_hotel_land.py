"""Tests: Hotel-Land (BT-40) tolerant aus Suite8 und in den Verkaeuferdaten.

Befund (Feld 11/2026): "Hotel-Land fehlt (WUSS.Hotelcountry -> XCOU.XCOU_ISO2)".
Das Kopf-SQL fand das Land nur, wenn WUSS.Hotelcountry buchstabengleich der
Langbezeichnung in XCOU entsprach, und es gab keine dauerhafte Abweichung.
"""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules import invoice_fetcher
from slim.api_slim import settings_api

SQL = (Path(__file__).resolve().parent.parent / "sql" / "invoice_header.sql").read_text(encoding="utf-8")


def _land_ausdruck() -> str:
    zeile = next(z for z in SQL.splitlines() if z.rstrip().rstrip(",").endswith("SupplierIdentificationCode"))
    return zeile.lower()


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "hotel.json").write_text(json.dumps({"hotel_code": "XYZ"}), encoding="utf-8")
    monkeypatch.setattr(settings_api, "CONFIG_DIR", cfg)
    monkeypatch.setattr(settings_api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings_api, "_suite8_seller_values", lambda: {})
    app = FastAPI()
    app.include_router(settings_api.router)
    return TestClient(app), cfg


def test_kopf_sql_findet_land_auch_ueber_iso_und_kurzname():
    a = _land_ausdruck()
    for spalte in ("xcou_longdesc", "xcou_iso2", "xcou_iso3", "xcou_custshortdesc"):
        assert spalte in a, spalte


def test_kopf_sql_schneidet_leerzeichen_ab():
    assert "trim(" in _land_ausdruck()


def test_kopf_sql_liefert_hoechstens_eine_zeile():
    # mehrere Treffer (Name und Kurzname verschiedener Laender) duerfen kein ORA-01427 geben
    assert "keep (dense_rank first" in _land_ausdruck()


def test_alter_kopf_override_wird_als_veraltet_erkannt():
    alt = SQL.replace("xcou_iso3", "xcou_isoX").replace("XCOU_ISO3", "XCOU_ISOX")
    assert invoice_fetcher._stale_override_markers("invoice_header.sql", alt)
    assert not invoice_fetcher._stale_override_markers("invoice_header.sql", SQL)


def test_fetcher_wendet_abweichendes_land_an(monkeypatch):
    monkeypatch.setattr(invoice_fetcher, "load_json",
                        lambda p, default=None: {"seller_overrides": {"supplieridentificationcode": " de "}})
    h = {"supplieridentificationcode": None}
    invoice_fetcher._apply_seller_overrides(h)
    assert h["supplieridentificationcode"] == "DE"


def test_land_steht_in_den_verkaeuferdaten(env):
    client, _ = env
    keys = [r["key"] for r in client.get("/api/settings/seller").json()]
    assert "supplieridentificationcode" in keys


def test_land_wird_als_iso2_gespeichert(env):
    client, cfg = env
    assert client.put("/api/settings/seller",
                      json={"values": {"supplieridentificationcode": "de"}}).status_code == 200
    saved = json.loads((cfg / "hotel.json").read_text(encoding="utf-8"))
    assert saved["seller_overrides"]["supplieridentificationcode"] == "DE"


@pytest.mark.parametrize("wert", ["Deutschland", "D", "DEU", "1e"])
def test_land_anders_als_zwei_buchstaben_wird_abgelehnt(env, wert):
    client, cfg = env
    r = client.put("/api/settings/seller", json={"values": {"supplieridentificationcode": wert}})
    assert r.status_code == 422
    assert "seller_overrides" not in json.loads((cfg / "hotel.json").read_text(encoding="utf-8"))


def test_land_leer_entfernt_die_abweichung(env):
    client, cfg = env
    client.put("/api/settings/seller", json={"values": {"supplieridentificationcode": "AT"}})
    client.put("/api/settings/seller", json={"values": {"supplieridentificationcode": ""}})
    saved = json.loads((cfg / "hotel.json").read_text(encoding="utf-8"))
    assert saved["seller_overrides"] == {}


def test_anzeige_nutzt_den_ausdruck_aus_dem_kopf_sql():
    class Cur:
        def execute(self, sql):
            self.sql = sql

        def fetchone(self):
            return ("DE",)
    cur = Cur()
    assert settings_api._suite8_land(cur) == "DE"
    assert cur.sql.startswith("select (select max(x.xcou_iso2)") and cur.sql.rstrip().endswith("from dual")
    assert "SupplierIdentificationCode" not in cur.sql
