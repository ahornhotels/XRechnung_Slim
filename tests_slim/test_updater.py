"""Tests für slim/core_slim/updater.py (inkrementeller File-Updater).

Der Updater lädt NICHT mehr ein Release-ZIP, sondern holt über die GitHub
Compare-API nur die geänderten Dateien einzeln (added/modified/removed) und
wendet sie unter Beachtung von UPDATE_TARGETS/PRESERVE an.
"""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from slim.core_slim import updater


# ─────────────────────────── Versions-Helfer ───────────────────────────

def test_parse_version_basic():
    assert updater._parse_version("1.5.0") == (1, 5, 0)
    assert updater._parse_version("v1.5.0") == (1, 5, 0)
    assert updater._parse_version("V2.0.0") == (2, 0, 0)


def test_parse_version_short():
    assert updater._parse_version("v1.5") == (1, 5, 0)
    assert updater._parse_version("3") == (3, 0, 0)


def test_parse_version_bad_input_returns_zeros():
    assert updater._parse_version("nightly") == (0, 0, 0)
    assert updater._parse_version("") == (0, 0, 0)


def test_parse_version_comparison():
    assert updater._parse_version("1.5.0") > updater._parse_version("1.4.4")
    assert updater._parse_version("v1.5.0") == updater._parse_version("1.5.0")
    assert updater._parse_version("2.0.0") > updater._parse_version("1.99.0")


# ─────────────────────────── Default-Ziel-Repo ───────────────────────────

def test_default_repo_points_to_slim_repo():
    # Nach der Ausgliederung muss der Updater auf das EIGENE Repo zeigen.
    assert updater.DEFAULT_OWNER == "ahornhotels"
    assert updater.DEFAULT_REPO == "XRechnung_Slim"


# ─────────────────────────── PRESERVE / Filter ───────────────────────────

def test_path_in_preserve():
    assert updater._path_in_preserve("slim/config") is True
    assert updater._path_in_preserve("slim/config/hotel.json") is True
    assert updater._path_in_preserve("slim/data") is True
    assert updater._path_in_preserve("install/instantclient") is True
    assert updater._path_in_preserve("install/instantclient/oci.dll") is True
    assert updater._path_in_preserve("slim/main_slim.py") is False
    assert updater._path_in_preserve("modules/xml_builder.py") is False


def test_should_update():
    # Top-Level in UPDATE_TARGETS UND nicht in PRESERVE
    assert updater._should_update("slim/main_slim.py") is True
    assert updater._should_update("modules/xml_builder.py") is True
    assert updater._should_update("VERSION") is True
    # In PRESERVE -> kein Update
    assert updater._should_update("slim/config/hotel.json") is False
    assert updater._should_update("slim/data/audit.jsonl") is False
    # Nicht in UPDATE_TARGETS -> ignoriert
    assert updater._should_update("install/python/python.exe") is False
    assert updater._should_update("validation/x/kosit.jar") is False


# ─────────────────────────── check_for_update ───────────────────────────

def test_check_for_update_no_release():
    fake_resp = MagicMock(status_code=404, text="Not Found")
    with patch.object(updater.httpx, "get", return_value=fake_resp):
        r = updater.check_for_update({"enabled": True, "owner": "x", "repo": "y"})
    assert r["available"] is False
    assert "Kein Release" in r["error"]


def test_check_for_update_newer_available():
    release_json = {
        "tag_name": "v9.9.9",
        "html_url": "https://github.com/x/y/releases/tag/v9.9.9",
        "body": "Bug fixes",
    }
    fake_resp = MagicMock(status_code=200, json=lambda: release_json)
    with patch.object(updater.httpx, "get", return_value=fake_resp):
        r = updater.check_for_update({"enabled": True, "owner": "x", "repo": "y"})
    assert r["available"] is True
    assert r["latest_version"] == "9.9.9"
    assert r["latest_tag"] == "v9.9.9"
    assert r["release_notes"] == "Bug fixes"
    # Kein ZIP-Asset-Feld mehr
    assert "asset_size_mb" not in r


def test_check_for_update_already_current():
    cv = updater.current_version()
    release_json = {"tag_name": f"v{cv}", "html_url": "x", "body": ""}
    fake_resp = MagicMock(status_code=200, json=lambda: release_json)
    with patch.object(updater.httpx, "get", return_value=fake_resp):
        r = updater.check_for_update({"enabled": True, "owner": "x", "repo": "y"})
    assert r["available"] is False
    assert r["current_version"] == r["latest_version"]


def test_check_for_update_disabled():
    r = updater.check_for_update({"enabled": False})
    assert r["available"] is False
    assert "deaktiviert" in r["error"]


# ─────────────────────────── Compare / Download ───────────────────────────

def test_compare_changed_files_parses_file_list():
    compare_json = {"files": [
        {"filename": "slim/main_slim.py", "status": "modified"},
        {"filename": "slim/old.py", "status": "removed"},
        {"filename": "modules/new.py", "status": "added"},
    ]}
    fake_resp = MagicMock(status_code=200, json=lambda: compare_json)
    with patch.object(updater.httpx, "get", return_value=fake_resp):
        files = updater.compare_changed_files("v1.0.0", "v1.1.0",
                                              {"owner": "x", "repo": "y"})
    names = {f["filename"]: f["status"] for f in files}
    assert names["slim/main_slim.py"] == "modified"
    assert names["slim/old.py"] == "removed"
    assert names["modules/new.py"] == "added"


def test_compare_changed_files_404_raises():
    fake_resp = MagicMock(status_code=404, text="Not Found")
    with patch.object(updater.httpx, "get", return_value=fake_resp):
        with pytest.raises(updater.CompareUnavailable):
            updater.compare_changed_files("vBOGUS", "v1.1.0",
                                          {"owner": "x", "repo": "y"})


def test_download_file_raw_uses_contents_api():
    fake_resp = MagicMock(status_code=200, content=b"file content")
    with patch.object(updater.httpx, "get", return_value=fake_resp) as g:
        data = updater.download_file_raw("slim/main_slim.py", "v1.1.0",
                                         {"owner": "o", "repo": "r"})
    assert data == b"file content"
    called_url = g.call_args[0][0]
    assert "/repos/o/r/contents/slim/main_slim.py" in called_url
    assert "ref=v1.1.0" in called_url


# ─────────────────────────── apply_incremental_update ───────────────────────────

def _files():
    return [
        {"filename": "slim/main_slim.py", "status": "modified"},
        {"filename": "modules/xml_builder.py", "status": "added"},
        {"filename": "slim/config/hotel.json", "status": "modified"},   # preserve
        {"filename": "install/python/python.exe", "status": "modified"},  # ignored
        {"filename": "slim/obsolete.py", "status": "removed"},          # delete
        {"filename": "VERSION", "status": "modified"},
    ]


def test_apply_incremental_dry_run():
    r = updater.apply_incremental_update(_files(), "v9.9.9", {}, dry_run=True)
    assert r["dry_run"] is True
    assert "slim/main_slim.py" in r["copied"]
    assert "modules/xml_builder.py" in r["copied"]
    assert "VERSION" in r["copied"]
    assert "slim/config/hotel.json" in r["preserved"]
    assert "slim/obsolete.py" in r["deleted"]
    # install/ ist nicht in UPDATE_TARGETS -> weder kopiert noch geloescht
    assert not any("install/" in x for x in r["copied"])
    assert not any("install/" in x for x in r["deleted"])


def test_apply_incremental_real_writes_preserves_deletes(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "APP_ROOT", tmp_path)
    monkeypatch.setattr(updater, "VERSION_FILE", tmp_path / "VERSION")
    # Bestehender Stand
    (tmp_path / "slim" / "config").mkdir(parents=True)
    (tmp_path / "slim" / "config" / "hotel.json").write_text(
        '{"hotel_code": "ORIG"}', encoding="utf-8")
    (tmp_path / "slim" / "main_slim.py").write_text("# OLD", encoding="utf-8")
    (tmp_path / "slim" / "obsolete.py").write_text("# weg damit", encoding="utf-8")
    (tmp_path / "VERSION").write_text("1.4.0", encoding="utf-8")

    def fake_download(path, ref, cfg):
        return {"slim/main_slim.py": b"# NEW",
                "modules/xml_builder.py": b"# builder",
                "VERSION": b"9.9.9"}[path]

    monkeypatch.setattr(updater, "download_file_raw", fake_download)
    r = updater.apply_incremental_update(_files(), "v9.9.9", {}, dry_run=False)

    assert (tmp_path / "slim" / "main_slim.py").read_text(encoding="utf-8") == "# NEW"
    assert (tmp_path / "modules" / "xml_builder.py").read_text(encoding="utf-8") == "# builder"
    assert (tmp_path / "VERSION").read_text(encoding="utf-8") == "9.9.9"
    # User-Config unangetastet
    assert "ORIG" in (tmp_path / "slim" / "config" / "hotel.json").read_text(encoding="utf-8")
    assert "slim/config/hotel.json" in r["preserved"]
    # Obsolete Datei geloescht
    assert not (tmp_path / "slim" / "obsolete.py").exists()
    assert "slim/obsolete.py" in r["deleted"]


# ─────────────────────────── perform_full_update ───────────────────────────

def test_perform_full_update_incremental(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "APP_ROOT", tmp_path)
    monkeypatch.setattr(updater, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(updater, "restart_service_detached", lambda: None)

    monkeypatch.setattr(updater, "check_for_update", lambda cfg=None: {
        "current_version": "1.0.0", "latest_version": "9.9.9",
        "latest_tag": "v9.9.9", "release_url": "u", "available": True,
    })
    monkeypatch.setattr(updater, "_resolve_base_ref", lambda cfg: "v1.0.0")
    monkeypatch.setattr(updater, "compare_changed_files",
                        lambda base, head, cfg: [{"filename": "VERSION", "status": "modified"}])
    monkeypatch.setattr(updater, "download_file_raw", lambda p, r, c: b"9.9.9")

    res = updater.perform_full_update({"enabled": True})
    assert res["applied"] is True
    assert res["to_version"] == "9.9.9"
    assert res["mode"] == "incremental"
    assert updater.load_state()["last_version"] == "9.9.9"


def test_perform_full_update_fallback_full(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "APP_ROOT", tmp_path)
    monkeypatch.setattr(updater, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(updater, "restart_service_detached", lambda: None)
    monkeypatch.setattr(updater, "check_for_update", lambda cfg=None: {
        "current_version": "0.0.0", "latest_version": "9.9.9",
        "latest_tag": "v9.9.9", "release_url": "u", "available": True,
    })
    # Kein Base -> Fallback auf vollen Tree-Abgleich
    monkeypatch.setattr(updater, "_resolve_base_ref", lambda cfg: None)
    monkeypatch.setattr(updater, "list_repo_files", lambda ref, cfg: ["VERSION", "slim/main_slim.py"])
    monkeypatch.setattr(updater, "download_file_raw", lambda p, r, c: b"x")

    res = updater.perform_full_update({"enabled": True})
    assert res["applied"] is True
    assert res["mode"] == "full"


def test_perform_full_update_already_current(monkeypatch):
    monkeypatch.setattr(updater, "check_for_update", lambda cfg=None: {
        "current_version": "9.9.9", "latest_version": "9.9.9",
        "available": False,
    })
    res = updater.perform_full_update({"enabled": True})
    assert res["applied"] is False


# ─────────────────────────── State ───────────────────────────

def test_state_persistence(tmp_path, monkeypatch):
    state_file = tmp_path / "update_state.json"
    monkeypatch.setattr(updater, "STATE_FILE", state_file)
    assert updater.load_state()["last_version"] is None
    updater.save_state({"last_version": "1.5.0", "applied_at": "2026-06-05T12:00:00Z"})
    assert updater.load_state()["last_version"] == "1.5.0"


def test_state_corrupt_file_returns_empty(tmp_path, monkeypatch):
    state_file = tmp_path / "update_state.json"
    state_file.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(updater, "STATE_FILE", state_file)
    assert updater.load_state()["last_version"] is None
