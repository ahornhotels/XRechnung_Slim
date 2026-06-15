"""Tests fuer slim/api_slim/config_api — Pattern lesen/schreiben/testen."""
import importlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Slim-Config-Dir auf tmp_path umlenken, hotel.json mit Defaults anlegen."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "hotel.json").write_text(json.dumps({
        "hotel_code": "TST",
        "currency": "EUR",
        "suite8_recognize_subject_pattern":
            r"Rechnung\s+Nr\.?\s*(?P<zinv_number>\d+)",
        "suite8_recognize_filename_pattern": "",
        "suite8_attachment_name_template": "{zinv_number}.xml",
    }), encoding="utf-8")

    monkeypatch.setenv("SUITE8_CONFIG_DIR", str(cfg_dir))
    # Reload damit CONFIG_DIR neu evaluiert wird
    import core.config_loader as cl
    importlib.reload(cl)
    # config_api importiert CONFIG_DIR aus cl — auch reloaden
    from slim.api_slim import config_api
    importlib.reload(config_api)

    app = FastAPI()
    app.include_router(config_api.router)
    return TestClient(app), cfg_dir


def test_get_pattern_returns_current(client):
    c, _ = client
    r = c.get("/api/config/pattern")
    assert r.status_code == 200
    j = r.json()
    assert "zinv_number" in j["suite8_recognize_subject_pattern"]
    assert j["suite8_recognize_filename_pattern"] == ""


def test_post_pattern_persists(client):
    c, cfg_dir = client
    payload = {
        "suite8_recognize_subject_pattern": r"Invoice\s+(?P<zinv_number>\d+)",
        "suite8_recognize_filename_pattern": "",
        "suite8_attachment_name_template": "{zinv_number}.xml",
    }
    r = c.post("/api/config/pattern", json=payload)
    assert r.status_code == 200
    cfg = json.loads((cfg_dir / "hotel.json").read_text(encoding="utf-8"))
    assert cfg["suite8_recognize_subject_pattern"] == payload["suite8_recognize_subject_pattern"]
    # Andere hotel.json-Felder bleiben (keine Zerstoerung)
    assert cfg["hotel_code"] == "TST"


def test_post_pattern_rejects_uncompilable(client):
    c, _ = client
    r = c.post("/api/config/pattern", json={
        "suite8_recognize_subject_pattern": "(unclosed",
        "suite8_recognize_filename_pattern": "",
        "suite8_attachment_name_template": "{zinv_number}.xml",
    })
    assert r.status_code == 400
    assert "Regex" in r.json()["detail"]


def test_post_pattern_rejects_missing_named_group(client):
    c, _ = client
    r = c.post("/api/config/pattern", json={
        "suite8_recognize_subject_pattern": r"Rechnung \d+",
        "suite8_recognize_filename_pattern": "",
        "suite8_attachment_name_template": "{zinv_number}.xml",
    })
    assert r.status_code == 400
    assert "zinv_number" in r.json()["detail"]


def test_post_pattern_rejects_both_empty(client):
    c, _ = client
    r = c.post("/api/config/pattern", json={
        "suite8_recognize_subject_pattern": "",
        "suite8_recognize_filename_pattern": "",
        "suite8_attachment_name_template": "{zinv_number}.xml",
    })
    assert r.status_code == 400
    assert "Mindestens eines" in r.json()["detail"]


def test_post_pattern_rejects_redos_length(client):
    c, _ = client
    r = c.post("/api/config/pattern", json={
        "suite8_recognize_subject_pattern": "a" * 600,
        "suite8_recognize_filename_pattern": "",
        "suite8_attachment_name_template": "{zinv_number}.xml",
    })
    # Pydantic max_length=500 blockt schon vor unserem validator (422)
    assert r.status_code in (400, 422)


def test_post_pattern_rejects_template_without_placeholder(client):
    c, _ = client
    r = c.post("/api/config/pattern", json={
        "suite8_recognize_subject_pattern": r"(?P<zinv_number>\d+)",
        "suite8_recognize_filename_pattern": "",
        "suite8_attachment_name_template": "rechnung.xml",
    })
    # Pydantic-Validator wirft 422 mit "Template braucht den Platzhalter"
    assert r.status_code == 422


def test_pattern_test_match_in_subject(client):
    c, _ = client
    r = c.post("/api/config/pattern/test", json={
        "subject_pattern": r"Rechnung Nr\.?\s*(?P<zinv_number>\d+)",
        "filename_pattern": "",
        "subject": "Wir sagen Danke - Ihre Rechnung Nr. 12345",
        "filename": "irrelevant.pdf",
    })
    assert r.status_code == 200
    j = r.json()
    assert j["matched"] is True
    assert j["result"] == "12345"
    assert j["kind"] == "zinv_number"
    assert j["source"] == "subject"


def test_pattern_test_match_filename_zinv_id(client):
    """Filename-Konvention: Suite8 schreibt ZINV_ID im PDF-Namen."""
    c, _ = client
    r = c.post("/api/config/pattern/test", json={
        "subject_pattern": "",
        "filename_pattern": r"Folio_(?P<zinv_id>\d+)\.pdf",
        "subject": "",
        "filename": "Folio_144853.pdf",
    })
    assert r.status_code == 200
    j = r.json()
    assert j["matched"] is True
    assert j["result"] == "144853"
    assert j["kind"] == "zinv_id"
    assert j["source"] == "filename"


def test_pattern_test_no_match(client):
    c, _ = client
    r = c.post("/api/config/pattern/test", json={
        "subject_pattern": r"Rechnung Nr\.?\s*(?P<zinv_number>\d+)",
        "filename_pattern": "",
        "subject": "Wir sagen Danke - Ihre Rechnung",
        "filename": "",
    })
    assert r.status_code == 200
    j = r.json()
    assert j["matched"] is False
    assert "Kein Match" in j["error"]


def test_pattern_test_ambiguous(client):
    c, _ = client
    r = c.post("/api/config/pattern/test", json={
        "subject_pattern": r"(?P<zinv_number>\d+)",
        "filename_pattern": r"(?P<zinv_number>\d+)",
        "subject": "Rechnung 111",
        "filename": "Folio_222.pdf",
    })
    j = r.json()
    assert j["matched"] is False
    assert "Ambiguous" in j["error"]


def test_pattern_test_returns_source_filename(client):
    c, _ = client
    r = c.post("/api/config/pattern/test", json={
        "subject_pattern": "",
        "filename_pattern": r"Folio_(?P<zinv_number>\d+)\.pdf",
        "subject": "",
        "filename": "Folio_99887.pdf",
    })
    j = r.json()
    assert j["matched"] is True
    assert j["result"] == "99887"
    assert j["kind"] == "zinv_number"
    assert j["source"] == "filename"


def test_pattern_test_invalid_pattern_returns_400(client):
    c, _ = client
    r = c.post("/api/config/pattern/test", json={
        "subject_pattern": "(broken",
        "filename_pattern": "",
        "subject": "",
        "filename": "",
    })
    assert r.status_code == 400


# ──────────────── pattern/generate (Nummer eintippen, kombiniert) ────────────

def test_pattern_generate_combines_two_languages(client):
    c, _ = client
    r = c.post("/api/config/pattern/generate", json={
        "examples": [
            {"example": "Wir sagen Danke - Ihre Rechnung Nr. 144853",
             "number": "144853"},
            {"example": "Your invoice - Invoice number 144853",
             "number": "144853"},
        ],
        "kind": "zinv_number",
    })
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert "(?:" in j["pattern"]
    assert "(?P<zinv_number>" in j["pattern"]


def test_pattern_generate_single_example(client):
    c, _ = client
    r = c.post("/api/config/pattern/generate", json={
        "examples": [
            {"example": "Ihre Rechnung Nr. 144853", "number": "144853"},
        ],
    })
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["matched"] == ["144853"]


def test_pattern_generate_requires_number(client):
    c, _ = client
    # number fehlt → Pydantic-Validierung 422
    r = c.post("/api/config/pattern/generate", json={
        "examples": [{"example": "Ihre Rechnung Nr. 144853"}],
    })
    assert r.status_code == 422


def test_pattern_generate_requires_at_least_one_example(client):
    c, _ = client
    r = c.post("/api/config/pattern/generate", json={"examples": []})
    assert r.status_code == 422


def test_pattern_generate_reports_number_not_standalone(client):
    c, _ = client
    r = c.post("/api/config/pattern/generate", json={
        "examples": [{"example": "Ihre Rechnung 144853", "number": "1448"}],
    })
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False
    assert j["error"]
