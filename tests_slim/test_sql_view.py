"""Tests fuer slim/api_slim/sql_view.py - Read-only SQL-Mapping-Viewer."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from slim.api_slim import sql_view


def _client():
    app = FastAPI()
    app.include_router(sql_view.router)
    return TestClient(app)


def test_list_templates_returns_metadata():
    r = _client().get("/api/sql/templates")
    assert r.status_code == 200
    j = r.json()
    names = [it["name"] for it in j["items"]]
    assert "invoice_header.sql" in names
    assert "invoice_lines.sql" in names
    assert "invoice_tax.sql" in names
    assert "invoice_totals.sql" in names
    # note muss erklaeren dass keine Views in der DB liegen
    assert "VIEW" in j["note"] or "View" in j["note"]


def test_get_template_returns_sql_body():
    r = _client().get("/api/sql/templates/invoice_header.sql")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert ":zinv_id" in r.text  # Bindvariable im SQL


def test_get_template_rejects_unknown_name():
    r = _client().get("/api/sql/templates/etc_passwd.sql")
    assert r.status_code == 404


def test_get_template_rejects_path_traversal():
    """Whitelist soll '../'-Tricks abblocken."""
    r = _client().get("/api/sql/templates/..%2Fconfig%2Fhotel.json")
    # FastAPI normalisiert %2F als / und matched die Route nicht mehr
    # -> 404, nicht 200 mit fremder Datei
    assert r.status_code in (404, 422)


def test_views_source_returns_original_doc():
    r = _client().get("/api/sql/views-source")
    if r.status_code == 404:
        # Datei optional - bei manchen Installationen nicht ausgepackt
        return
    assert r.status_code == 200
    # Inhalt muss CREATE VIEW oder CREATE FUNCTION enthalten
    text = r.text.upper()
    assert "CREATE OR REPLACE" in text
