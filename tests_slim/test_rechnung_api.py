"""Tests fuer slim/api_slim/rechnung_api — Detailseite einer Rechnung:
wartend (Vorschau live), gesendet (Archivdatei), nie erzeugt (nachtraeglich
erzeugen, nur Download)."""
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules import xml_builder
from modules.kosit_validator import KositValidationError
from slim.api_slim import archive_api, rechnung_api
from slim.api_slim import status as status_api
from slim.core_slim import archive_fs, audit_jsonl, overrides
from tests_slim.test_creditnote_xsd import _base_invoice

CFG = {"suite8_recognize_subject_pattern": r"Rechnung (?P<zinv_number>\d+)",
       "suite8_recognize_filename_pattern": "",
       "suite8_attachment_name_template": "XRechnung_{zinv_number}.xml"}


def _inv(nr="100231", **header):
    inv = _base_invoice(role=0, duedate="2026-07-29", id=nr,
                        **{"customerendpointid": "ap@kunde.example", **header})
    inv["lines"][0].update(lineextensionamount="100.00", lineextensionamountnet="100.00",
                           priceamount="100.00", itemname="Übernachtung")
    inv["tax_breakdown"][0].update(taxableamount="100.00", taxamount="19.00")
    inv["totals"].update(invoicenet=100.0, invoicegross=119.0,
                         invoicetaxtotal=19.0, taxexclusiveamount=100.0)
    return inv


def _mail(wmai_id=7, nr="100231"):
    return {"wmai_id": wmai_id, "filename": "Rechnung.pdf", "subject": f"Ihre Rechnung {nr}",
            "to": "einkauf@kunde.example"}


@pytest.fixture
def umgebung(tmp_path):
    """Test-App; Suite8 ist vollstaendig ersetzt. Rueckgabe: (client, data_dir, welt).
    welt steuert, was 'Suite8' liefert: wartende Mails, Rechnungen je Nummer."""
    app = FastAPI()
    app.include_router(rechnung_api.router)
    status_api.get_state().update({"data_dir": tmp_path, "interval_seconds": 30,
                                   "last_run": None, "last_run_summary": None})
    archive_api._BUCKET_CACHE.clear()
    welt = {"mails": [], "rechnungen": {}, "fehler": {}, "kosit": None}
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock(name="conn"))
    cm.__exit__ = MagicMock(return_value=None)

    def _kosit(xml):
        if welt["kosit"] is not None:
            raise welt["kosit"]

    with ExitStack() as st:
        p = lambda *a, **k: st.enter_context(patch.object(*a, **k))
        p(rechnung_api, "load_hotel_config", return_value=dict(CFG))
        p(rechnung_api, "get_connection", return_value=cm)
        p(rechnung_api, "find_pending_wmai", side_effect=lambda conn, limit=50, **k: list(welt["mails"]))
        p(rechnung_api, "get_wmai_error", side_effect=lambda wid, conn: welt["fehler"].get(wid))
        p(rechnung_api.invoice_fetcher, "find_zinv_id_by_number",
          side_effect=lambda nr: 1000 + int(nr) if nr in welt["rechnungen"] else None)
        p(rechnung_api.invoice_fetcher, "fetch_invoice",
          side_effect=lambda zid: welt["rechnungen"].get(str(zid - 1000)))
        p(rechnung_api.kosit_validator, "validate", side_effect=_kosit)
        yield TestClient(app), tmp_path, welt


def _gesendet(data_dir, nr="100231"):
    xml = xml_builder.build_and_validate(_inv(nr))
    r = archive_fs.save_xml(data_dir, nr, xml, filename=f"XRechnung_{nr}.xml",
                            now=datetime(2026, 11, 1, tzinfo=timezone.utc),
                            meta={"wmai_id": 5, "empfaenger": "ap@kunde.example"})
    archive_fs.mark_sent(r["xml_path"], 5, "ap@kunde.example")
    return r, xml


def _dateien(data_dir):
    return sorted(p.relative_to(data_dir).as_posix() for p in Path(data_dir).rglob("*") if p.is_file())


# ───────────────────────── wartende Rechnung ─────────────────────────

def test_wartende_rechnung_zeigt_vorschau_fehler_und_mail(umgebung):
    c, dd, welt = umgebung
    welt["mails"] = [_mail()]
    welt["rechnungen"]["100231"] = _inv(customerpostalzone="", customercityname="")
    welt["fehler"][7] = "zinv=100231: Validator-Fail: 2 Issues"
    j = c.get("/api/rechnung", params={"nr": "100231"}).json()
    assert j["zustand"] == "wartet" and j["quelle"] == "vorschau"
    assert j["wartend"]["wmai_id"] == 7 and j["wartend"]["to"] == "einkauf@kunde.example"
    assert j["wartend"]["error"].startswith("zinv=100231")
    assert j["ansicht"]["kaeufer"]["name"] == "Kunde AG"
    assert j["ansicht"]["positionen"][0]["bezeichnung"] == "Übernachtung"
    assert len(j["pruefung"]["pflichtfelder"]) == 2


def test_wartende_rechnung_ueber_wmai_id(umgebung):
    c, dd, welt = umgebung
    welt["mails"] = [_mail(wmai_id=9, nr="100240")]
    welt["rechnungen"]["100240"] = _inv("100240")
    j = c.get("/api/rechnung", params={"wmai_id": 9}).json()
    assert j["nr"] == "100240" and j["zustand"] == "wartet"
    assert j["pruefung"]["pflichtfelder"] == [] and j["pruefung"]["bau_fehler"] is None


def test_vorschau_wendet_override_an(umgebung):
    c, dd, welt = umgebung
    welt["mails"] = [_mail()]
    welt["rechnungen"]["100231"] = _inv(customerpostalzone="")
    overrides.save(dd, 7, {"customerpostalzone": "99999"})
    j = c.get("/api/rechnung", params={"nr": "100231"}).json()
    assert j["pruefung"]["pflichtfelder"] == []
    assert "99999" in j["ansicht"]["kaeufer"]["ort"]
    assert j["wartend"]["override"] == {"customerpostalzone": "99999"}


def test_ansehen_schreibt_nichts(umgebung):
    """Ein GET darf nichts veraendern: keine Datei, kein Protokoll, keine Metadaten."""
    c, dd, welt = umgebung
    welt["mails"] = [_mail()]
    welt["rechnungen"]["100231"] = _inv()
    vorher = _dateien(dd)
    assert c.get("/api/rechnung", params={"nr": "100231"}).status_code == 200
    assert c.get("/api/rechnung/kosit", params={"nr": "100231"}).json()["ok"] is True
    assert _dateien(dd) == vorher


# ───────────────────────── gesendete Rechnung ─────────────────────────

def test_gesendete_rechnung_kommt_aus_dem_archiv(umgebung):
    c, dd, welt = umgebung
    _gesendet(dd)
    # Suite8 zeigt heute einen anderen Kunden - die Seite muss trotzdem das Archiv zeigen
    welt["rechnungen"]["100231"] = _inv(customername="Heute Anders GmbH",
                                         customerregistrationname="Heute Anders GmbH")
    j = c.get("/api/rechnung", params={"nr": "100231"}).json()
    assert j["zustand"] == "gesendet" and j["quelle"] == "archiv"
    assert j["ansicht"]["kaeufer"]["name"] == "Kunde AG"
    a = j["archiv"][0]
    assert a["status"] == "gesendet" and a["echt"] is True and a["empfaenger"] == "ap@kunde.example"
    assert a["rel_path"].endswith("XRechnung_100231.xml")


def test_heutiger_stand_wird_live_gebaut_und_schreibt_nichts(umgebung):
    c, dd, welt = umgebung
    _gesendet(dd)
    welt["rechnungen"]["100231"] = _inv(customername="Heute Anders GmbH",
                                         customerregistrationname="Heute Anders GmbH")
    vorher = _dateien(dd)
    j = c.get("/api/rechnung", params={"nr": "100231", "fassung": "aktuell"}).json()
    assert j["zustand"] == "gesendet" and j["quelle"] == "vorschau"
    assert j["ansicht"]["kaeufer"]["name"] == "Heute Anders GmbH"
    assert _dateien(dd) == vorher


def test_archiv_wird_auch_ohne_datenbank_gezeigt(umgebung):
    c, dd, welt = umgebung
    _gesendet(dd)
    with patch.object(rechnung_api, "get_connection", side_effect=RuntimeError("ORA-12541")):
        j = c.get("/api/rechnung", params={"nr": "100231"}).json()
    assert j["zustand"] == "gesendet" and j["ansicht"]["fakten"]["rechnung"] == "100231"
    assert "ORA-12541" in j["db_fehler"]


def test_nummer_wird_exakt_gesucht_nicht_als_teilstring(umgebung):
    c, dd, welt = umgebung
    _gesendet(dd, "100231")
    assert c.get("/api/rechnung", params={"nr": "10023"}).status_code == 404


def test_verlauf_enthaelt_nur_eintraege_dieser_rechnung(umgebung):
    c, dd, welt = umgebung
    _gesendet(dd)
    audit_jsonl.record(dd, "attach_ok", wmai_id=5, zinv_number="100231", details={"sha256": "x"})
    audit_jsonl.record(dd, "attach_ok", wmai_id=6, zinv_number="100232", details={})
    audit_jsonl.record(dd, "override_saved", wmai_id=5, details={"by": "verwalter"})
    j = c.get("/api/rechnung", params={"nr": "100231"}).json()
    assert [e["event"] for e in j["verlauf"]] == ["attach_ok", "override_saved"]


# ───────────────────────── nie erzeugt / nachtraeglich ─────────────────────────

def test_nie_erzeugte_rechnung_zeigt_vorschau(umgebung):
    c, dd, welt = umgebung
    welt["rechnungen"]["100300"] = _inv("100300")
    j = c.get("/api/rechnung", params={"nr": "100300"}).json()
    assert j["zustand"] == "nie_erzeugt" and j["quelle"] == "vorschau" and j["archiv"] == []
    assert j["ansicht"]["fakten"]["rechnung"] == "100300"


def test_unbekannte_rechnung_404(umgebung):
    c, dd, welt = umgebung
    r = c.get("/api/rechnung", params={"nr": "999999"})
    assert r.status_code == 404 and "999999" in r.json()["detail"]


def test_nachtraeglich_erzeugen_legt_gekennzeichnet_ab(umgebung):
    c, dd, welt = umgebung
    welt["rechnungen"]["100300"] = _inv("100300")
    r = c.post("/api/rechnung/erzeugen", json={"nr": "100300"})
    assert r.status_code == 200, r.text
    rel = r.json()["rel_path"]
    assert rel.endswith("XRechnung_100300.xml") and (dd / "xml" / rel).is_file()
    j = c.get("/api/rechnung", params={"nr": "100300"}).json()
    assert j["zustand"] == "nachtraeglich" and j["quelle"] == "archiv"
    assert j["archiv"][0]["status"] == "nachträglich erzeugt" and j["archiv"][0]["echt"] is True
    ev = [e for e in audit_jsonl.tail(dd) if e["event"] == "nachtraeglich_erzeugt"]
    assert len(ev) == 1 and ev[0]["zinv_number"] == "100300" and ev[0]["details"]["sha256"]


def test_nachtraeglich_erzeugen_gesperrt_wenn_schon_im_archiv(umgebung):
    c, dd, welt = umgebung
    r0, xml = _gesendet(dd)
    welt["rechnungen"]["100231"] = _inv(customername="Heute Anders GmbH")
    r = c.post("/api/rechnung/erzeugen", json={"nr": "100231"})
    assert r.status_code == 409 and "Archiv" in r.json()["detail"]
    assert Path(r0["xml_path"]).read_bytes() == xml          # Archivdatei unangetastet


def test_nachtraeglich_erzeugen_kein_zweites_mal(umgebung):
    c, dd, welt = umgebung
    welt["rechnungen"]["100300"] = _inv("100300")
    assert c.post("/api/rechnung/erzeugen", json={"nr": "100300"}).status_code == 200
    assert c.post("/api/rechnung/erzeugen", json={"nr": "100300"}).status_code == 409


def test_nachtraeglich_erzeugen_gesperrt_solange_mail_wartet(umgebung):
    c, dd, welt = umgebung
    welt["mails"] = [_mail(nr="100300")]
    welt["rechnungen"]["100300"] = _inv("100300")
    r = c.post("/api/rechnung/erzeugen", json={"nr": "100300"})
    assert r.status_code == 409 and "wartet" in r.json()["detail"]
    assert not (dd / "xml").exists()


def test_nachtraeglich_erzeugen_nur_fehlerfrei(umgebung):
    c, dd, welt = umgebung
    welt["rechnungen"]["100300"] = _inv("100300", customerpostalzone="")
    r = c.post("/api/rechnung/erzeugen", json={"nr": "100300"})
    assert r.status_code == 422 and "PLZ" in r.json()["detail"]
    welt["rechnungen"]["100300"] = _inv("100300")
    welt["kosit"] = KositValidationError(["BR-DE-1: Zahlungsanweisung fehlt"])
    r = c.post("/api/rechnung/erzeugen", json={"nr": "100300"})
    assert r.status_code == 422 and "BR-DE-1" in r.json()["detail"]
    welt["kosit"] = FileNotFoundError("java fehlt")
    assert c.post("/api/rechnung/erzeugen", json={"nr": "100300"}).status_code == 503
    assert not (dd / "xml").exists()


def test_nachtraeglich_erzeugen_ohne_datenbank_kein_blindflug(umgebung):
    """Ist nicht pruefbar, ob eine Mail wartet, wird nichts erzeugt."""
    c, dd, welt = umgebung
    welt["rechnungen"]["100300"] = _inv("100300")
    with patch.object(rechnung_api, "get_connection", side_effect=RuntimeError("ORA-12541")):
        assert c.post("/api/rechnung/erzeugen", json={"nr": "100300"}).status_code == 503
    assert not (dd / "xml").exists()


# ───────────────────────── KoSIT auf Knopfdruck ─────────────────────────

def test_kosit_meldet_befunde(umgebung):
    c, dd, welt = umgebung
    welt["rechnungen"]["100300"] = _inv("100300")
    welt["kosit"] = KositValidationError(["BR-DE-1: Zahlungsanweisung fehlt"])
    j = c.get("/api/rechnung/kosit", params={"nr": "100300"}).json()
    assert j["ok"] is False and j["befunde"] == ["BR-DE-1: Zahlungsanweisung fehlt"]


def test_kosit_nicht_verfuegbar(umgebung):
    c, dd, welt = umgebung
    welt["rechnungen"]["100300"] = _inv("100300")
    welt["kosit"] = FileNotFoundError("java fehlt")
    j = c.get("/api/rechnung/kosit", params={"nr": "100300"}).json()
    assert j["ok"] is None and "java fehlt" in j["hinweis"]


# ───────────────────────── Archivliste ─────────────────────────

def test_archivliste_nennt_nachtraeglich_erzeugte(umgebung):
    c, dd, welt = umgebung
    welt["rechnungen"]["100300"] = _inv("100300")
    c.post("/api/rechnung/erzeugen", json={"nr": "100300"})
    app = FastAPI()
    app.include_router(archive_api.router)
    items = TestClient(app).get("/api/archive").json()["items"]
    assert items[0]["status"] == "nachträglich erzeugt"


# ───────────────────────── Rollen ─────────────────────────

def test_erzeugen_nur_fuer_verwalter_ansehen_fuer_alle():
    from slim.api_slim import auth_api
    assert auth_api._needs_admin("POST", "/api/rechnung/erzeugen") is True
    assert auth_api._needs_admin("GET", "/api/rechnung") is False
    assert auth_api._needs_admin("GET", "/api/rechnung/kosit") is False
