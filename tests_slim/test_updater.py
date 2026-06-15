"""Tests für slim/core_slim/updater.py."""
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from slim.core_slim import updater


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


def test_find_slim_asset_correct_name():
    release = {"assets": [
        {"name": "Suite8XRechnungSetup_1.5.0.exe"},
        {"name": "Suite8XRechnungSlim-1.5.0.zip", "browser_download_url": "x"},
    ]}
    asset = updater.find_slim_asset(release)
    assert asset["name"] == "Suite8XRechnungSlim-1.5.0.zip"


def test_find_slim_asset_no_match():
    release = {"assets": [{"name": "anderes.zip"}]}
    assert updater.find_slim_asset(release) is None


def test_path_in_preserve():
    assert updater._path_in_preserve("slim/config") is True
    assert updater._path_in_preserve("slim/config/hotel.json") is True
    assert updater._path_in_preserve("slim/data") is True
    assert updater._path_in_preserve("install/instantclient") is True
    assert updater._path_in_preserve("install/instantclient/oci.dll") is True
    assert updater._path_in_preserve("slim/main_slim.py") is False
    assert updater._path_in_preserve("modules/xml_builder.py") is False


def test_check_for_update_no_release(monkeypatch):
    """404 von GitHub -> klare Fehlermeldung."""
    fake_resp = MagicMock(status_code=404, text="Not Found")
    with patch.object(updater.httpx, "get", return_value=fake_resp):
        r = updater.check_for_update({"enabled": True, "owner": "x", "repo": "y"})
    assert r["available"] is False
    assert "Kein Release" in r["error"]


def test_check_for_update_newer_available(monkeypatch):
    """Mock GitHub-Release-Response mit höherer Version."""
    release_json = {
        "tag_name": "v9.9.9",
        "html_url": "https://github.com/x/y/releases/tag/v9.9.9",
        "body": "Bug fixes",
        "assets": [{
            "name": "Suite8XRechnungSlim-9.9.9.zip",
            "size": 144_000_000,
            "browser_download_url": "https://example.com/slim.zip",
        }],
    }
    fake_resp = MagicMock(status_code=200, json=lambda: release_json)
    with patch.object(updater.httpx, "get", return_value=fake_resp):
        r = updater.check_for_update({"enabled": True, "owner": "x", "repo": "y"})
    assert r["available"] is True
    assert r["latest_version"] == "9.9.9"
    assert r["latest_tag"] == "v9.9.9"
    assert r["asset_size_mb"] == 137.3


def test_check_for_update_already_current(monkeypatch):
    """Wenn Tag = aktuelle Version, ist available=False."""
    cv = updater.current_version()
    release_json = {
        "tag_name": f"v{cv}",
        "html_url": "x",
        "body": "",
        "assets": [{
            "name": f"Suite8XRechnungSlim-{cv}.zip",
            "size": 1, "browser_download_url": "x",
        }],
    }
    fake_resp = MagicMock(status_code=200, json=lambda: release_json)
    with patch.object(updater.httpx, "get", return_value=fake_resp):
        r = updater.check_for_update({"enabled": True, "owner": "x", "repo": "y"})
    assert r["available"] is False
    assert r["current_version"] == r["latest_version"]


def test_check_for_update_disabled(monkeypatch):
    r = updater.check_for_update({"enabled": False})
    assert r["available"] is False
    assert "deaktiviert" in r["error"]


def test_apply_update_dry_run():
    """Dry-Run zeigt welche Files kopiert würden ohne zu schreiben.
    Granular auf File-Ebene."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("slim/main_slim.py", "# slim entry")
        zf.writestr("modules/xml_builder.py", "# updated")
        zf.writestr("slim/data/audit-2026-06.jsonl", "USER DATA")
        zf.writestr("slim/config/hotel.json", "INJECTED")
        zf.writestr("install/python/python.exe", "FAKE")
        zf.writestr("VERSION", "9.9.9")

    r = updater.apply_update_from_zip(buf.getvalue(), dry_run=True)
    assert r["dry_run"] is True
    # echte Updates
    assert "slim/main_slim.py" in r["copied"]
    assert "modules/xml_builder.py" in r["copied"]
    assert "VERSION" in r["copied"]
    # User-Data + bundled Binaries werden NICHT kopiert
    assert "slim/data/audit-2026-06.jsonl" in r["preserved"]
    assert "slim/config/hotel.json" in r["preserved"]
    # install/ ist gar nicht in UPDATE_TARGETS -> still ignoriert
    assert not any("install/" in x for x in r["copied"])


def test_apply_update_real_preserves_user_config(tmp_path, monkeypatch):
    """User-Configs in slim/config/ bleiben nach Update unverändert."""
    monkeypatch.setattr(updater, "APP_ROOT", tmp_path)
    monkeypatch.setattr(updater, "VERSION_FILE", tmp_path / "VERSION")

    # Vorhandene Files
    (tmp_path / "slim" / "config").mkdir(parents=True)
    (tmp_path / "slim" / "config" / "hotel.json").write_text(
        '{"hotel_code": "ORIG"}', encoding="utf-8",
    )
    (tmp_path / "slim" / "main_slim.py").write_text("# OLD", encoding="utf-8")
    (tmp_path / "VERSION").write_text("1.4.0", encoding="utf-8")

    # Update-ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("slim/main_slim.py", "# NEW")
        zf.writestr("VERSION", "1.5.0")
        zf.writestr("slim/config/hotel.json", '{"hotel_code": "INJECTED"}')

    r = updater.apply_update_from_zip(buf.getvalue(), dry_run=False)

    # main_slim.py + VERSION wurden aktualisiert
    assert (tmp_path / "slim" / "main_slim.py").read_text(encoding="utf-8") == "# NEW"
    assert (tmp_path / "VERSION").read_text(encoding="utf-8") == "1.5.0"
    # User-Config UNVERAENDERT (PRESERVE-Schutz)
    assert "ORIG" in (tmp_path / "slim" / "config" / "hotel.json").read_text(encoding="utf-8")
    assert "slim/config/hotel.json" in r["preserved"]


def test_state_persistence(tmp_path, monkeypatch):
    """save_state + load_state Round-Trip."""
    state_file = tmp_path / "update_state.json"
    monkeypatch.setattr(updater, "STATE_FILE", state_file)

    assert updater.load_state()["last_version"] is None
    updater.save_state({"last_version": "1.5.0", "applied_at": "2026-06-05T12:00:00Z"})
    s = updater.load_state()
    assert s["last_version"] == "1.5.0"


def test_state_corrupt_file_returns_empty(tmp_path, monkeypatch):
    state_file = tmp_path / "update_state.json"
    state_file.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(updater, "STATE_FILE", state_file)
    s = updater.load_state()
    assert s["last_version"] is None  # tolerant
