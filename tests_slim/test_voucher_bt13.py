"""Tests: Bestellnummer des Kaeufers (BT-13) aus einem waehlbaren Suite8-Feld.

Fuer die Abrechnung mit Reiseveranstaltern kommt eine Nummer von der
Reservierung als BT-13 (cac:OrderReference/cbc:ID) in die XRechnung. Welches
Feld das ist, haengt vom Haus ab: Die Voucher-Nummer liegt z. B. in einem
angepassten Feld, das es nicht in jeder Suite8 gibt. Der Installer waehlt
deshalb unter Konfiguration XRechnung -> Bestellnummer (BT-13) ein Feld der
Tabellen YRES oder YRCF aus; die Auswahl liest Slim aus der Datenbank.

Eine Sammelrechnung ueber mehrere Reservierungen traegt alle Werte, durch
Komma getrennt.
"""
import json
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from modules import invoice_fetcher, xml_builder
from slim.core_slim import settings_schema
from tests_slim.test_creditnote_xsd import _CN_XSD, _INV_XSD, _assert_xsd_valid, _base_invoice
from tests_slim.test_deposit_allowances import _invoice, _line
from tests_slim.test_settings_api import _field, env  # noqa: F401  (env ist eine Fixture)

NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}
VOUCHER = ("YRCF", "YRCF_VOUCHERNO")


class _Cur:
    def __init__(self, rows=None, fehler=None):
        self.rows, self.fehler, self.sql = rows or [], fehler, None

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params
        if self.fehler:
            raise self.fehler

    def fetchall(self):
        return self.rows


def _rechnung(**kopf):
    """Normale Rechnung: eine Position Logis, 100,00 netto zu 7 %."""
    inv = _invoice([_line("Logis", 107.0, 100.0, 7)], 107.0, 100.0, 7.0)
    inv["header"].update(kopf)
    return inv


def _bt13(xml: bytes):
    doc = etree.fromstring(xml)
    return [e.text for e in doc.findall("cac:OrderReference/cbc:ID", NS)]


def _sql(cur):
    return " ".join(cur.sql.upper().split())


# ── Werte lesen ──

def test_feld_an_yrcf_wird_ueber_die_reservierung_gelesen():
    cur = _Cur([("  TUI123456 ",)])
    assert invoice_fetcher._bt13_werte(cur, 4711, *VOUCHER) == "TUI123456"
    assert cur.params == {"zinv_id": 4711}
    assert "C.YRCF_VOUCHERNO" in _sql(cur)
    assert "C.YRCF_YRES_ID = Z.ZPOS_ORIGINATED_YRES_ID" in _sql(cur)


def test_feld_an_yres_wird_direkt_gelesen():
    cur = _Cur([("AB-1",)])
    assert invoice_fetcher._bt13_werte(cur, 1, "YRES", "YRES_EXTERNALREF") == "AB-1"
    assert "C.YRES_EXTERNALREF" in _sql(cur)
    assert "C.YRES_ID = Z.ZPOS_ORIGINATED_YRES_ID" in _sql(cur)


def test_mehrere_werte_ohne_doppelte_und_leere():
    cur = _Cur([("B2",), ("A1",), (" A1",), (None,), ("  ",)])
    assert invoice_fetcher._bt13_werte(cur, 1, *VOUCHER) == "A1, B2"


def test_zahlenfelder_ohne_nachkommastellen():
    cur = _Cur([(4711.0,), (Decimal("12"),), (7,)])
    assert invoice_fetcher._bt13_werte(cur, 1, "YRES", "YRES_NUMMER") == "12, 4711, 7"


def test_kein_wert_ergibt_none():
    assert invoice_fetcher._bt13_werte(_Cur([]), 1, *VOUCHER) is None


def test_fehlende_spalte_blockiert_die_rechnung_nicht():
    cur = _Cur(fehler=Exception('ORA-00904: "C"."YRCF_VOUCHERNO": invalid identifier'))
    assert invoice_fetcher._bt13_werte(cur, 1, *VOUCHER) is None


def test_anderer_datenbankfehler_wird_gemeldet():
    with pytest.raises(Exception, match="ORA-03113"):
        invoice_fetcher._bt13_werte(_Cur(fehler=Exception("ORA-03113: end-of-file")), 1, *VOUCHER)


def test_nur_yres_und_yrcf_und_nur_saubere_spaltennamen():
    for tabelle, spalte in (("ZINV", "ZINV_ID"), ("YRCF", "X FROM DUAL --"), ("YRCF", "yrcf_voucherno"), ("YRCF", "")):
        with pytest.raises(ValueError):
            invoice_fetcher._bt13_werte(_Cur([]), 1, tabelle, spalte)


# ── Einstellung lesen ──

def _lies(monkeypatch, werte):
    monkeypatch.setattr(invoice_fetcher, "load_json", lambda p, default=None: werte)
    return invoice_fetcher._bt13_feld()


def test_einstellung_lesen(monkeypatch):
    assert _lies(monkeypatch, {"bt13_feld": "YRCF.YRCF_VOUCHERNO"}) == VOUCHER
    assert _lies(monkeypatch, {"bt13_feld": " yres.yres_externalref "}) == ("YRES", "YRES_EXTERNALREF")
    assert _lies(monkeypatch, {"bt13_feld": ""}) is None


def test_ungueltige_einstellung_gilt_als_aus(monkeypatch):
    for wert in ("ZINV.ZINV_ID", "YRCF.X; drop table wmai", "YRCF_VOUCHERNO", True, 5):
        assert _lies(monkeypatch, {"bt13_feld": wert}) is None, wert


def test_fehlende_einstellung_nimmt_den_standard(monkeypatch):
    erwartet = tuple(invoice_fetcher.BT13_FELD_STANDARD.split(".")) if invoice_fetcher.BT13_FELD_STANDARD else None
    assert _lies(monkeypatch, {}) == erwartet


# ── Auswahl aus der Datenbank ──

def _katalog(monkeypatch, rows=None, fehler=None):
    class _Conn:
        def cursor(self):
            return _Cur(rows, fehler)

    @contextmanager
    def _fake():
        if fehler and not rows:
            raise fehler
        yield _Conn()

    monkeypatch.setattr(invoice_fetcher, "get_connection", _fake)


def test_auswahl_listet_text_und_zahlenfelder_beider_tabellen(monkeypatch):
    _katalog(monkeypatch, [("YRCF", "YRCF_VOUCHERNO", "VARCHAR2", 1000),
                           ("YRES", "YRES_ID", "NUMBER", 22),
                           ("YRES", "YRES_NAME$", "VARCHAR2", 60)])   # kein sauberer Name: nicht anbieten
    assert invoice_fetcher.bt13_feldauswahl() == [
        ("YRCF.YRCF_VOUCHERNO", "YRCF.YRCF_VOUCHERNO – Text (1000)"),
        ("YRES.YRES_ID", "YRES.YRES_ID – Zahl"),
    ]


def test_auswahl_fragt_nur_die_beiden_tabellen_des_eigenen_schemas(monkeypatch):
    gesehen = {}

    class _C(_Cur):
        def execute(self, sql, params=None):
            gesehen["sql"] = " ".join(sql.upper().split())

    class _Conn:
        def cursor(self):
            return _C()

    @contextmanager
    def _fake():
        yield _Conn()

    monkeypatch.setattr(invoice_fetcher, "get_connection", _fake)
    invoice_fetcher.bt13_feldauswahl()
    assert "FROM USER_TAB_COLUMNS" in gesehen["sql"]
    assert "'YRES'" in gesehen["sql"] and "'YRCF'" in gesehen["sql"]
    assert gesehen["sql"].startswith("SELECT")


def test_auswahl_ohne_datenbank_ist_leer(monkeypatch):
    _katalog(monkeypatch, fehler=RuntimeError("DB nicht erreichbar"))
    assert invoice_fetcher.bt13_feldauswahl() == []


# ── Einstellung in der Oberflaeche ──

def test_einstellung_ist_eine_auswahl_und_fuer_installer_erklaert():
    sec = settings_schema.section("bestellnummer")
    assert sec.page == "xrechnung" and sec.label == "Bestellnummer (BT-13)"
    assert [s.key for s in sec.settings] == ["bt13_feld"]
    s = sec.settings[0]
    assert s.type == "select" and s.default == invoice_fetcher.BT13_FELD_STANDARD
    assert "Installer" in s.label
    for wort in ("Bestellnummer des Käufers", "Installer", "YRES", "YRCF"):
        assert wort in s.help, wort
    for wort in ("Was ist BT-13", "Bestellnummer des Käufers", "Reiseveranstalter", "Voucher",
                 "Screen Painting", "schon genutzt", "Installer", "Komma", "BT-10", "Leitweg-ID"):
        assert wort in s.info, wort


def test_speichern_prueft_tabelle_und_spaltennamen():
    s = settings_schema.section("bestellnummer").settings[0]
    assert settings_schema.coerce(s, "") == ""
    assert settings_schema.coerce(s, "YRCF.YRCF_VOUCHERNO") == "YRCF.YRCF_VOUCHERNO"
    for wert in ("ZINV.ZINV_ID", "YRCF.X; drop table wmai", "YRCF_VOUCHERNO", "yrcf.yrcf_voucherno"):
        with pytest.raises(settings_schema.SettingError):
            settings_schema.coerce(s, wert)


def test_api_liefert_die_felder_der_datenbank_zur_auswahl(env, monkeypatch):
    client, _, _ = env
    _katalog(monkeypatch, [("YRCF", "YRCF_VOUCHERNO", "VARCHAR2", 1000)])
    f = _field(client.get("/api/settings?page=xrechnung").json(), "bestellnummer", "bt13_feld")
    assert f["type"] == "select"
    assert f["choices"] == ["", "YRCF.YRCF_VOUCHERNO"]
    assert f["labels"][""].startswith("aus")
    assert f["labels"]["YRCF.YRCF_VOUCHERNO"] == "YRCF.YRCF_VOUCHERNO – Text (1000)"


def test_api_ohne_datenbank_behaelt_den_gespeicherten_wert(env, monkeypatch):
    client, cfg, _ = env
    _katalog(monkeypatch, fehler=RuntimeError("DB nicht erreichbar"))
    assert client.put("/api/settings/bestellnummer",
                      json={"values": {"bt13_feld": "YRCF.YRCF_VOUCHERNO"}}).status_code == 200
    assert json.loads((cfg / "hotel.json").read_text(encoding="utf-8"))["bt13_feld"] == "YRCF.YRCF_VOUCHERNO"
    f = _field(client.get("/api/settings").json(), "bestellnummer", "bt13_feld")
    assert f["value"] == "YRCF.YRCF_VOUCHERNO" and f["choices"] == [""]


def test_handbuch_liest_fuer_die_auswahl_keine_datenbank(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setattr(invoice_fetcher, "get_connection",
                        lambda: (_ for _ in ()).throw(AssertionError("keine DB im Handbuch")))
    from slim.api_slim import settings_api
    client.app.include_router(settings_api.handbuch_router)
    assert client.get("/api/handbuch/einstellungen").status_code == 200


def test_seite_zeigt_beschriftungen_der_auswahl():
    src = (Path(settings_schema.__file__).resolve().parents[1] / "frontend" / "settings.html").read_text(encoding="utf-8")
    assert "f.labels" in src


# ── fetch_invoice ──

def _fetch(monkeypatch, feld):
    """fetch_invoice gegen eine Attrappe; liefert (Kopf, ausgefuehrte SQLs)."""
    rows = {"invoice_header.sql": ({"ID": "1", "BUYERREFERENCE": "Muster GmbH",
                                    "DOCUMENTCURRENCYCODE": "EUR"},)}
    sqls = []

    class _FCur:
        def execute(self, sql, params=None):
            sqls.append(sql)
            self.sql = sql
            self.rows = rows.get(sql, ())
            self.description = [(c,) for c in (self.rows[0].keys() if self.rows else ())]

        def fetchall(self):
            if "YRCF_VOUCHERNO" in self.sql:
                return [("TUI123456",)]
            return [tuple(r.values()) for r in self.rows]

        def fetchone(self):
            return None

    class _Conn:
        def cursor(self):
            return _FCur()

    @contextmanager
    def _fake_conn():
        yield _Conn()

    monkeypatch.setattr(invoice_fetcher, "get_connection", _fake_conn)
    monkeypatch.setattr(invoice_fetcher, "_read_sql", lambda name: name)
    monkeypatch.setattr(invoice_fetcher, "_resolve_billing_reference_from_payment", lambda c, h: None)
    monkeypatch.setattr(invoice_fetcher, "_bt10_freitexte", lambda: [])
    monkeypatch.setattr(invoice_fetcher, "_bt13_feld", lambda: feld)
    return invoice_fetcher.fetch_invoice(1)["header"], sqls


def test_mit_gewaehltem_feld_kommt_der_wert_in_den_kopf(monkeypatch):
    kopf, _ = _fetch(monkeypatch, VOUCHER)
    assert kopf["orderreferenceid"] == "TUI123456"


def test_ohne_gewaehltes_feld_wird_nichts_gelesen(monkeypatch):
    kopf, sqls = _fetch(monkeypatch, None)
    assert "orderreferenceid" not in kopf
    assert not any("YRCF" in s.upper() for s in sqls)


# ── XML ──

def test_rechnung_mit_bestellnummer_hat_bt13_und_bleibt_schemagueltig():
    xml = xml_builder.render(_rechnung(orderreferenceid="TUI123456"))
    assert _bt13(xml) == ["TUI123456"]
    _assert_xsd_valid(xml, _INV_XSD)


def test_rechnung_ohne_bestellnummer_hat_kein_bt13():
    xml = xml_builder.render(_rechnung())
    assert _bt13(xml) == []
    _assert_xsd_valid(xml, _INV_XSD)


def test_gutschrift_mit_bestellnummer_hat_bt13_und_bleibt_schemagueltig():
    inv = _base_invoice(3, orderreferenceid="TUI123456")
    xml = xml_builder.render(inv)
    assert _bt13(xml) == ["TUI123456"]
    _assert_xsd_valid(xml, _CN_XSD)


def test_sonderzeichen_werden_maskiert():
    assert _bt13(xml_builder.render(_rechnung(orderreferenceid="A&B<1>"))) == ["A&B<1>"]
