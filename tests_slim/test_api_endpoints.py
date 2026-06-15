"""Tests fuer slim/api_slim — Status, Pending, Retry, Audit-Tail."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from slim.api_slim import status as status_api
from slim.api_slim import retry as retry_api
from slim.core_slim import audit_jsonl


@pytest.fixture
def client(tmp_path):
    """Baut einen Slim-FastAPI-Test-App mit isoliertem data_dir."""
    app = FastAPI()
    app.include_router(status_api.router)
    app.include_router(retry_api.router)
    state = status_api.get_state()
    state.update({"data_dir": tmp_path, "interval_seconds": 30,
                  "last_run": None, "last_run_summary": None})
    return TestClient(app), tmp_path, state


def test_status_returns_state(client):
    c, _, state = client
    state["last_run"] = "2026-06-03T12:00:00Z"
    state["last_run_summary"] = {"attached": 3, "failed": 0,
                                 "no_match": 0, "ambiguous": 0}
    with patch.object(status_api, "load_hotel_config",
                      return_value={"hotel_code": "HHB"}):
        r = c.get("/api/status")
    assert r.status_code == 200
    j = r.json()
    assert j["hotel"] == "HHB"
    assert j["interval_seconds"] == 30
    assert j["last_run_summary"]["attached"] == 3


def test_pending_returns_db_data(client):
    c, _, _ = client
    conn = MagicMock(name="conn")
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=None)

    with patch.object(status_api, "get_connection", return_value=cm), \
         patch.object(status_api, "find_pending_wmai",
                      return_value=[
                          {"wmai_id": 11, "filename": "Folio_IND_1.pdf",
                           "subject": "Mail", "to": "x@y.z"}]), \
         patch.object(status_api, "get_wmai_error", return_value="Letzter Fehler"):
        r = c.get("/api/pending")
    assert r.status_code == 200
    j = r.json()
    assert j["count"] == 1
    assert j["items"][0]["error"] == "Letzter Fehler"


def test_pending_503_on_db_failure(client):
    c, _, _ = client
    with patch.object(status_api, "get_connection",
                      side_effect=RuntimeError("DB tot")):
        r = c.get("/api/pending")
    assert r.status_code == 503


def test_audit_tail_returns_recorded(client, tmp_path):
    c, dd, _ = client
    audit_jsonl.record(dd, "attach_ok", wmai_id=1, zinv_number="A")
    audit_jsonl.record(dd, "pattern_no_match", wmai_id=2)
    r = c.get("/api/audit/tail?n=10")
    j = r.json()
    assert j["count"] == 2
    events = [e["event"] for e in j["items"]]
    assert "attach_ok" in events and "pattern_no_match" in events


def test_audit_tail_caps_n_at_2000(client):
    c, _, _ = client
    r = c.get("/api/audit/tail?n=999999")
    # FastAPI Query(le=2000) -> 422
    assert r.status_code == 422


def test_retry_clears_wmai_error_and_audits(client, tmp_path):
    c, dd, _ = client
    conn = MagicMock(name="conn")
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=None)
    with patch.object(retry_api, "get_connection", return_value=cm), \
         patch.object(retry_api, "set_wmai_error") as setter:
        r = c.post("/api/wmai/42/retry")
    assert r.status_code == 200
    setter.assert_called_once()
    # 2. Argument muss None sein (Clear)
    assert setter.call_args[0][1] is None
    # JSONL retry_triggered geschrieben
    files = sorted(dd.glob("audit-*.jsonl"))
    entries = [json.loads(l) for l in files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(e["event"] == "retry_triggered" and e["wmai_id"] == 42 for e in entries)


def test_retry_503_on_db_failure(client):
    c, _, _ = client
    with patch.object(retry_api, "get_connection",
                      side_effect=RuntimeError("oops")):
        r = c.post("/api/wmai/1/retry")
    assert r.status_code == 503
