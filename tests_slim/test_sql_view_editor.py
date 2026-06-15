"""Tests fuer slim/api_slim/sql_view.py - PUT/DELETE/validate-Endpoints."""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from slim.api_slim import sql_view, status as status_api
from slim.core_slim import sql_overrides


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(sql_view.router)
    state = status_api.get_state()
    state["data_dir"] = tmp_path
    return TestClient(app), tmp_path


def test_list_templates_shows_override_status(client):
    c, dd = client
    sql_overrides.save(dd, "invoice_header.sql",
                        "SELECT :zinv_id FROM dual")
    j = c.get("/api/sql/templates").json()
    by_name = {it["name"]: it for it in j["items"]}
    assert by_name["invoice_header.sql"]["overridden"] is True
    assert by_name["invoice_lines.sql"]["overridden"] is False
    # expected_bind ist mit dabei (UI braucht das fuer Hinweise)
    assert by_name["invoice_header.sql"]["expected_bind"] == ":zinv_id"


def test_get_template_returns_override_when_present(client):
    c, dd = client
    sql_overrides.save(dd, "invoice_header.sql",
                        "-- MARKER\nSELECT :zinv_id FROM dual")
    r = c.get("/api/sql/templates/invoice_header.sql")
    assert "MARKER" in r.text


def test_get_template_source_always_returns_repo(client):
    """Auch wenn Override aktiv: /source liefert das Repo-File."""
    c, dd = client
    sql_overrides.save(dd, "invoice_header.sql",
                        "-- MARKER\nSELECT :zinv_id FROM dual")
    r = c.get("/api/sql/templates/invoice_header.sql/source")
    assert r.status_code == 200
    # Repo-File enthaelt das Original-Header-Kommentar
    assert "MARKER" not in r.text
    assert ":zinv_id" in r.text


def test_validate_endpoint_accepts_clean_sql(client):
    c, _ = client
    r = c.post("/api/sql/templates/invoice_header.sql/validate", json={
        "sql": "SELECT * FROM zinv WHERE zinv_id = :zinv_id",
    })
    j = r.json()
    assert j["ok"] is True
    assert j["error"] is None


def test_validate_endpoint_rejects_dml(client):
    c, _ = client
    r = c.post("/api/sql/templates/invoice_header.sql/validate", json={
        "sql": "DELETE FROM zinv WHERE :zinv_id = :zinv_id",
    })
    j = r.json()
    assert j["ok"] is False
    assert "DELETE" in j["error"] or "SELECT" in j["error"]


def test_put_template_saves_override(client):
    c, dd = client
    sql = "-- Test-Override\nSELECT * FROM zinv WHERE zinv_id = :zinv_id"
    r = c.put("/api/sql/templates/invoice_header.sql", json={"sql": sql})
    assert r.status_code == 200 and r.json()["overridden"] is True
    # Filesystem-Verifikation
    assert sql_overrides.load(dd, "invoice_header.sql") == sql


def test_put_template_400_on_validation_error(client):
    c, dd = client
    r = c.put("/api/sql/templates/invoice_header.sql", json={
        "sql": "DROP TABLE zinv",
    })
    assert r.status_code == 400
    assert "DROP" in r.json()["detail"] or "SELECT" in r.json()["detail"]
    # Nichts wurde geschrieben
    assert sql_overrides.load(dd, "invoice_header.sql") is None


def test_delete_template_removes_override(client):
    c, dd = client
    sql_overrides.save(dd, "invoice_header.sql",
                        "SELECT :zinv_id FROM dual")
    r = c.delete("/api/sql/templates/invoice_header.sql")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert sql_overrides.load(dd, "invoice_header.sql") is None


def test_delete_template_idempotent(client):
    c, _ = client
    r = c.delete("/api/sql/templates/invoice_header.sql")
    assert r.status_code == 200 and r.json()["deleted"] is False


def test_put_unknown_template_400(client):
    c, _ = client
    r = c.put("/api/sql/templates/etc_passwd.sql", json={
        "sql": "SELECT :zinv_id FROM dual",
    })
    # validate() wirft ValidationError -> 400
    assert r.status_code in (400, 404)
