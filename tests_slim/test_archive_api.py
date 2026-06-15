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
