"""Tests fuer slim/api_slim/archive_api — Listing, Download, SHA256-Verify."""
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from slim.api_slim import archive_api
from slim.api_slim import status as status_api
from slim.core_slim import archive_fs


@pytest.fixture
def client(tmp_path):
    """Slim-Test-App mit isoliertem data_dir (gleiches State-Muster wie status)."""
    app = FastAPI()
    app.include_router(archive_api.router)
    state = status_api.get_state()
    state.update({"data_dir": tmp_path, "interval_seconds": 30,
                  "last_run": None, "last_run_summary": None})
    return TestClient(app), tmp_path


def _archive(tmp_path, zinv, content, filename=None, kosit=None,
             month=6, mtime=None):
    r = archive_fs.save_xml(
        tmp_path, zinv, content, kosit_report=kosit, filename=filename,
        now=datetime(2026, month, 1, tzinfo=timezone.utc),
    )
    if mtime is not None:
        os.utime(r["xml_path"], (mtime, mtime))
    return r


# ---------------------------------------------------------------- Listing

def test_list_empty_when_no_archive_dir(client):
    c, _ = client
    r = c.get("/api/archive")
    assert r.status_code == 200
    assert r.json() == {"items": [], "count": 0}


def test_sort_items_nach_zeitpunkt_nicht_string():
    """Neueste zuerst nach Epoch — nicht nach dem mtime-Anzeigestring, dessen
    lexikografische Ordnung ueber einen DST-Wechsel (+01:00/+02:00) falsch ist.
    'b' hat den groesseren mtime-String, aber den aelteren Zeitpunkt."""
    items = [
        {"name": "a_neu", "_ts": 200.0, "mtime": "2026-10-25T02:30:00+01:00"},
        {"name": "b_alt", "_ts": 100.0, "mtime": "2026-10-25T02:45:00+02:00"},
    ]
    out = archive_api._sort_items(list(items))
    assert [i["name"] for i in out] == ["a_neu", "b_alt"]


def test_list_returns_entries_with_fields(client):
    c, tmp_path = client
    _archive(tmp_path, "144853", b"<a/>",
             filename="XRechnung_144853.xml", kosit=b"<report/>")
    r = c.get("/api/archive")
    assert r.status_code == 200
    j = r.json()
    assert j["count"] == 1
    item = j["items"][0]
    assert item["name"] == "XRechnung_144853.xml"
    assert item["bucket"] == "2026/06"
    assert item["size"] == len(b"<a/>")
    assert item["has_sha256"] is True
    assert item["has_kosit_report"] is True
    assert "mtime" in item
    # rel_path ist relativ zum xml-Root und nutzt Forward-Slashes
    assert item["rel_path"] == "2026/06/XRechnung_144853.xml"


def test_list_excludes_kosit_reports_as_entries(client):
    c, tmp_path = client
    _archive(tmp_path, "1", b"<a/>", kosit=b"<report/>")
    r = c.get("/api/archive")
    names = [i["name"] for i in r.json()["items"]]
    assert names == ["1.xml"]


def test_list_sorted_newest_first(client):
    c, tmp_path = client
    _archive(tmp_path, "alt", b"<a/>", mtime=1_000_000)
    _archive(tmp_path, "neu", b"<b/>", mtime=2_000_000)
    r = c.get("/api/archive")
    names = [i["name"] for i in r.json()["items"]]
    assert names == ["neu.xml", "alt.xml"]


def test_list_filters_by_q_case_insensitive(client):
    c, tmp_path = client
    _archive(tmp_path, "144853", b"<a/>", filename="XRechnung_144853.xml")
    _archive(tmp_path, "999", b"<b/>")
    r = c.get("/api/archive", params={"q": "xrechnung"})
    names = [i["name"] for i in r.json()["items"]]
    assert names == ["XRechnung_144853.xml"]


def test_list_respects_limit(client):
    c, tmp_path = client
    for i in range(5):
        _archive(tmp_path, f"nr{i}", b"<x/>", mtime=1_000_000 + i)
    r = c.get("/api/archive", params={"limit": 2})
    j = r.json()
    assert j["count"] == 2
    assert [i["name"] for i in j["items"]] == ["nr4.xml", "nr3.xml"]


# --------------------------------------------------------------- Download

def test_download_xml(client):
    c, tmp_path = client
    _archive(tmp_path, "144853", b"<Invoice/>")
    r = c.get("/api/archive/file", params={"path": "2026/06/144853.xml"})
    assert r.status_code == 200
    assert r.content == b"<Invoice/>"
    assert "attachment" in r.headers["content-disposition"]
    assert "144853.xml" in r.headers["content-disposition"]


def test_download_sha256_sidecar(client):
    c, tmp_path = client
    _archive(tmp_path, "144853", b"<Invoice/>")
    r = c.get("/api/archive/file", params={"path": "2026/06/144853.sha256"})
    assert r.status_code == 200
    assert "144853.xml" in r.text


def test_download_blocks_traversal(client):
    c, tmp_path = client
    secret = tmp_path / "geheim.xml"
    secret.write_text("<top-secret/>")
    r = c.get("/api/archive/file", params={"path": "../geheim.xml"})
    assert r.status_code == 404


def test_download_blocks_absolute_path(client):
    c, tmp_path = client
    secret = tmp_path / "geheim.xml"
    secret.write_text("<top-secret/>")
    r = c.get("/api/archive/file", params={"path": str(secret)})
    assert r.status_code == 404


def test_download_blocks_disallowed_extension(client):
    c, tmp_path = client
    bucket = tmp_path / "xml" / "2026" / "06"
    bucket.mkdir(parents=True)
    (bucket / "notiz.txt").write_text("x")
    r = c.get("/api/archive/file", params={"path": "2026/06/notiz.txt"})
    assert r.status_code == 404


def test_download_missing_file_404(client):
    c, _ = client
    r = c.get("/api/archive/file", params={"path": "2026/06/fehlt.xml"})
    assert r.status_code == 404


# ----------------------------------------------------------------- Verify

def test_verify_ok(client):
    c, tmp_path = client
    r0 = _archive(tmp_path, "144853", b"<Invoice/>")
    r = c.get("/api/archive/verify", params={"path": "2026/06/144853.xml"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["expected"] == j["actual"] == r0["sha256"]


def test_verify_detects_tampering(client):
    c, tmp_path = client
    r0 = _archive(tmp_path, "144853", b"<Invoice/>")
    Path(r0["xml_path"]).write_bytes(b"<Manipuliert/>")
    r = c.get("/api/archive/verify", params={"path": "2026/06/144853.xml"})
    j = r.json()
    assert j["ok"] is False
    assert j["expected"] == r0["sha256"]
    assert j["actual"] != r0["sha256"]


def test_verify_missing_sidecar(client):
    c, tmp_path = client
    r0 = _archive(tmp_path, "144853", b"<Invoice/>")
    Path(r0["xml_path"]).with_suffix(".sha256").unlink()
    r = c.get("/api/archive/verify", params={"path": "2026/06/144853.xml"})
    j = r.json()
    assert j["ok"] is False
    assert j["expected"] is None


def test_verify_blocks_traversal(client):
    c, tmp_path = client
    r = c.get("/api/archive/verify", params={"path": "../../etc/passwd.xml"})
    assert r.status_code == 404


# ---------------------------------------------------------------- Archiv fuer Pruefer

import hashlib as _hashlib
import json as _json

NS = ('xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
      'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
      'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"')


def _inv(nr, datum, betrag="100.00"):
    return (f'<?xml version="1.0"?><Invoice {NS}><cbc:ID>{nr}</cbc:ID><cbc:IssueDate>{datum}</cbc:IssueDate>'
            f'<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>'
            f'<cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="EUR">{betrag}</cbc:PayableAmount>'
            f'</cac:LegalMonetaryTotal></Invoice>').encode()


def test_filter_rechnungsdatum(client):
    c, tmp_path = client
    for nr, d in (("900001", "2026-10-31"), ("900002", "2026-11-01"), ("900003", "2026-11-30")):
        _archive(tmp_path, nr, _inv(nr, d))
    j = c.get("/api/archive", params={"von": "2026-11-01", "bis": "2026-11-30"}).json()
    assert sorted(i["rechnung"] for i in j["items"]) == ["900002", "900003"]
    assert j["items"][0]["rechnungsdatum"] == "2026-11-30"      # neuestes Rechnungsdatum zuerst


def test_filter_datum_ungueltig_422(client):
    c, _ = client
    assert c.get("/api/archive", params={"von": "31.10.2026"}).status_code == 422


def test_suche_rechnungsnummer(client):
    c, tmp_path = client
    _archive(tmp_path, "900001", _inv("900001", "2026-11-01"), filename="XR_A.xml")
    _archive(tmp_path, "900002", _inv("900002", "2026-11-01"), filename="XR_B.xml")
    j = c.get("/api/archive", params={"q": "900002"}).json()
    assert [i["name"] for i in j["items"]] == ["XR_B.xml"]


def test_status_und_zuletzt_gesendet(client):
    c, tmp_path = client
    a = _archive(tmp_path, "900001", _inv("900001", "2026-11-01"), mtime=1_000_000)
    archive_fs.mark_sent(a["xml_path"], 1, "a@example.com",
                         now=datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc))
    b = _archive(tmp_path, "900001", _inv("900001", "2026-11-01", "90.00"), mtime=2_000_000)
    archive_fs.mark_sent(b["xml_path"], 2, "a@example.com",
                         now=datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc))
    _archive(tmp_path, "900001", _inv("900001", "2026-11-01", "80.00"), mtime=3_000_000)   # Anhaengen gescheitert
    items = c.get("/api/archive").json()["items"]
    assert len(items) == 3
    by_betrag = {i["betrag"]: i for i in items}
    assert by_betrag["80.00"]["status"] == "nicht angehängt"
    assert by_betrag["90.00"]["status"] == "gesendet" and by_betrag["90.00"]["zuletzt_gesendet"] is True
    assert by_betrag["100.00"]["zuletzt_gesendet"] is False and by_betrag["100.00"]["version"] is True
    assert [i["zuletzt_gesendet"] for i in items].count(True) == 1


def test_bestand_ohne_audit_status_unbekannt(client):
    c, tmp_path = client
    r = _archive(tmp_path, "900001", _inv("900001", "2026-11-01"))
    Path(r["xml_path"]).with_suffix(".meta.json").unlink()
    item = c.get("/api/archive").json()["items"][0]
    assert item["status"] == "unbekannt" and item["rechnungsdatum"] == "2026-11-01"


def test_echtheit_in_liste(client):
    c, tmp_path = client
    r = _archive(tmp_path, "900001", _inv("900001", "2026-11-01"))
    assert c.get("/api/archive").json()["items"][0]["echt"] is True
    Path(r["xml_path"]).write_bytes(_inv("900001", "2026-11-01", "1.00"))
    assert c.get("/api/archive").json()["items"][0]["echt"] is False


def test_kosit_nur_wenn_vorhanden(client):
    c, tmp_path = client
    _archive(tmp_path, "900001", _inv("900001", "2026-11-01"), kosit=b"<r/>")
    _archive(tmp_path, "900002", _inv("900002", "2026-11-01"))
    by = {i["rechnung"]: i for i in c.get("/api/archive").json()["items"]}
    assert by["900001"]["kosit_report"].endswith("900001.kosit-report.xml")
    assert by["900002"]["kosit_report"] is None


def test_ansicht_rechnung(client):
    c, tmp_path = client
    r = _archive(tmp_path, "900001", _inv("900001", "2026-11-01", "42.00"))
    rel = Path(r["xml_path"]).relative_to(tmp_path / "xml").as_posix()
    j = c.get("/api/archive/ansicht", params={"path": rel}).json()
    assert j["fakten"]["rechnung"] == "900001" and j["summen"]["zahlbetrag"] == "42.00"
    assert "<Invoice" in j["xml"]


def test_ansicht_pfad_ausserhalb_404(client):
    c, _ = client
    assert c.get("/api/archive/ansicht", params={"path": "../../config/connection.json"}).status_code == 404


def test_ansicht_keine_xrechnung_422(client):
    c, tmp_path = client
    r = _archive(tmp_path, "1", b"<a/>")
    rel = Path(r["xml_path"]).relative_to(tmp_path / "xml").as_posix()
    assert c.get("/api/archive/ansicht", params={"path": rel}).status_code == 422


def test_liste_korrigiert_archiviert_bei_attach_ok(client):
    """mark_sent scheiterte nach geglücktem Anhängen: das Protokoll (attach_ok mit
    sha256) belegt den Versand, die Liste zeigt 'gesendet' und merkt es sich."""
    from slim.core_slim import audit_jsonl
    c, tmp_path = client
    xml = _inv("900001", "2026-11-01")
    r = _archive(tmp_path, "900001", xml)
    audit_jsonl.record(tmp_path, "attach_ok", wmai_id=7, zinv_number="900001",
                       details={"xml_path": r["xml_path"], "sha256": _hashlib.sha256(xml).hexdigest()})
    item = c.get("/api/archive").json()["items"][0]
    assert item["status"] == "gesendet" and item["angehaengt_am"]
    meta = _json.loads(Path(r["xml_path"]).with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "gesendet" and meta["wmai_id"] == 7


def test_liste_liest_unveraenderte_monate_nicht_neu(client, monkeypatch):
    c, tmp_path = client
    archive_api._BUCKET_CACHE.clear()
    for i in range(3):
        _archive(tmp_path, f"90000{i}", _inv(f"90000{i}", "2026-11-01"))
    bucket = tmp_path / "xml" / "2026" / "11"
    if not bucket.is_dir():
        bucket = next(d for d in (tmp_path / "xml").glob("*/*") if d.is_dir())
    alt = 1_700_000_000
    os.utime(bucket, (alt, alt))                    # Ordner laenger nicht geaendert
    calls = []
    orig = archive_fs.ensure_meta
    monkeypatch.setattr(archive_fs, "ensure_meta", lambda p, idx: calls.append(p) or orig(p, idx))
    assert c.get("/api/archive").json()["count"] == 3
    first = len(calls)
    assert first == 3
    assert c.get("/api/archive").json()["count"] == 3
    assert len(calls) == first                      # Monat unveraendert: nichts neu gelesen
    _archive(tmp_path, "900009", _inv("900009", "2026-11-02"))
    assert c.get("/api/archive").json()["count"] == 4


def test_nachtrag_im_hintergrund(tmp_path):
    r = archive_fs.save_xml(tmp_path, "900001", _inv("900001", "2026-11-01"))
    Path(r["xml_path"]).with_suffix(".meta.json").unlink()
    assert archive_fs.nachtragen(tmp_path) == 1
    assert Path(r["xml_path"]).with_suffix(".meta.json").exists()
    assert archive_fs.nachtragen(tmp_path) == 0


def test_frisch_geaenderter_monat_wird_nicht_zwischengespeichert(client, monkeypatch):
    # Windows-Zeitstempel sind grob: kommt eine Datei im selben Zeitschritt
    # wie das Lesen hinzu, aendert sich die Ordnerzeit nicht. Ein gerade erst
    # geaenderter Ordner darf deshalb nicht zwischengespeichert werden.
    c, tmp_path = client
    archive_api._BUCKET_CACHE.clear()
    _archive(tmp_path, "900001", _inv("900001", "2026-11-01"))
    bucket = next(d for d in (tmp_path / "xml").glob("*/*") if d.is_dir())
    jetzt = bucket.stat().st_mtime
    assert c.get("/api/archive").json()["count"] == 1
    _archive(tmp_path, "900002", _inv("900002", "2026-11-01"))
    os.utime(bucket, (jetzt, jetzt))                # gleicher Zeitschritt
    assert c.get("/api/archive").json()["count"] == 2
