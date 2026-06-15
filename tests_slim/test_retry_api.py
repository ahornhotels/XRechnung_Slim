"""Tests fuer slim/api_slim/retry.py — single retry + bulk + override-API."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from slim.api_slim import retry as retry_api
from slim.api_slim import status as status_api
from slim.core_slim import overrides


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(retry_api.router)
    state = status_api.get_state()
    state.update({"data_dir": tmp_path, "interval_seconds": 30,
                  "last_run": None, "last_run_summary": None})
    return TestClient(app), tmp_path


def _mock_conn():
    conn = MagicMock(name="conn")
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=None)
    return cm, conn


# ── Bulk-Retry ──

def test_bulk_retry_clears_only_wmais_with_error(client):
    c, dd = client
    cm, conn = _mock_conn()
    pending_rows = [
        {"wmai_id": 1, "filename": "", "subject": "", "to": ""},
        {"wmai_id": 2, "filename": "", "subject": "", "to": ""},
        {"wmai_id": 3, "filename": "", "subject": "", "to": ""},
    ]
    # WMAI 1 + 3 haben Fehler, 2 ist sauber
    errors_by_id = {1: "Validator-Fail", 2: None, 3: "kosit_fail"}

    with patch.object(retry_api, "get_connection", return_value=cm), \
         patch.object(retry_api, "find_pending_wmai", return_value=pending_rows), \
         patch.object(retry_api, "get_wmai_error",
                      side_effect=lambda wid, conn: errors_by_id[wid]), \
         patch.object(retry_api, "set_wmai_error") as setter:
        r = c.post("/api/wmai/retry-all")

    assert r.status_code == 200
    j = r.json()
    assert j["cleared_count"] == 2
    assert set(j["cleared_ids"]) == {1, 3}
    # set_wmai_error wurde nur fuer 1 und 3 gerufen
    cleared_ids = {call.args[0] for call in setter.call_args_list}
    assert cleared_ids == {1, 3}


def test_bulk_retry_records_audit(client):
    c, dd = client
    cm, conn = _mock_conn()
    with patch.object(retry_api, "get_connection", return_value=cm), \
         patch.object(retry_api, "find_pending_wmai",
                      return_value=[{"wmai_id": 1, "filename": "",
                                     "subject": "", "to": ""}]), \
         patch.object(retry_api, "get_wmai_error", return_value="err"), \
         patch.object(retry_api, "set_wmai_error"):
        c.post("/api/wmai/retry-all")

    files = sorted(dd.glob("audit-*.jsonl"))
    assert len(files) == 1
    entries = [json.loads(l) for l in files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    bulk = [e for e in entries if e["event"] == "retry_triggered"
            and (e.get("details") or {}).get("bulk") is True]
    assert bulk and bulk[0]["details"]["cleared_count"] == 1


def test_bulk_retry_db_503(client):
    c, _ = client
    with patch.object(retry_api, "get_connection",
                      side_effect=RuntimeError("ORA-...")):
        r = c.post("/api/wmai/retry-all")
    assert r.status_code == 503


# ── Override-API ──

def test_override_get_initial_empty(client):
    c, _ = client
    r = c.get("/api/wmai/77/override")
    assert r.status_code == 200
    j = r.json()
    assert j["wmai_id"] == 77
    assert j["values"] == {}
    assert "customerendpointid" in j["allowed_keys"]


def test_override_post_saves_and_clears_error(client):
    c, dd = client
    cm, conn = _mock_conn()
    with patch.object(retry_api, "get_connection", return_value=cm), \
         patch.object(retry_api, "set_wmai_error") as setter:
        r = c.post("/api/wmai/77/override", json={"values": {
            "customerendpointid": "x@y.z",
            "customername": "Mustermann",
        }})
    assert r.status_code == 200
    j = r.json()
    assert j["saved"] == {"customerendpointid": "x@y.z",
                          "customername": "Mustermann"}
    # WMAI_ERROR=NULL wurde gesetzt (implizites Retry)
    setter.assert_called_once_with(77, None, conn)
    # Datei wirklich geschrieben
    assert overrides.load(dd, 77) == {"customerendpointid": "x@y.z",
                                       "customername": "Mustermann"}


def test_override_post_rejects_disallowed_keys(client):
    c, _ = client
    r = c.post("/api/wmai/77/override", json={"values": {
        "id": "FAKE-INVOICE-ID",  # nicht erlaubt
    }})
    assert r.status_code == 400
    assert "id" in r.json()["detail"]


def test_override_delete(client):
    c, dd = client
    overrides.save(dd, 88, {"customername": "Tmp"})
    r = c.delete("/api/wmai/88/override")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert overrides.load(dd, 88) == {}


def test_override_delete_idempotent(client):
    c, _ = client
    r = c.delete("/api/wmai/99/override")
    assert r.status_code == 200 and r.json()["deleted"] is False


def test_overrides_list(client):
    c, dd = client
    overrides.save(dd, 1, {"customername": "A"})
    overrides.save(dd, 2, {"customername": "B"})
    r = c.get("/api/overrides")
    assert r.status_code == 200
    items = r.json()["items"]
    assert "1" in items or 1 in items  # JSON-Keys sind Strings nach Roundtrip
