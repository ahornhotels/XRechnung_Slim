"""Tests: /api/schalter - XRechnung ein/aus ueber den Suite8-Trigger."""
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from slim.api_slim import schalter_api
from slim.api_slim import status as status_api
from slim.core_slim.trigger_state import TriggerSchaltFehler


@pytest.fixture
def client(tmp_path):
    app = FastAPI()

    @app.middleware("http")
    async def _user(request, call_next):
        request.state.user = "verwalter1"
        return await call_next(request)

    app.include_router(schalter_api.router)
    status_api.get_state().update({"data_dir": tmp_path})
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock(name="conn"))
    cm.__exit__ = MagicMock(return_value=None)
    with patch.object(schalter_api, "get_connection", return_value=cm):
        yield TestClient(app), tmp_path


def _audit(tmp_path):
    out = []
    for f in tmp_path.glob("audit-*.jsonl"):
        out += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


def _st(state):
    return {"state": state, "owner": "V8LIVE", "user": "V8LIVE", "grant_sql": None, "error": None}


def test_get_liefert_zustand(client):
    c, _ = client
    with patch.object(schalter_api.trigger_state, "read_state", return_value=_st("aktiv")):
        r = c.get("/api/schalter")
    assert r.status_code == 200 and r.json()["state"] == "aktiv"


def test_post_schaltet_und_auditiert(client):
    c, dd = client
    with patch.object(schalter_api.trigger_state, "read_state", return_value=_st("aktiv")), \
         patch.object(schalter_api.trigger_state, "set_enabled", return_value=_st("inaktiv")) as se:
        r = c.post("/api/schalter", json={"ein": False})
    assert r.status_code == 200 and r.json()["state"] == "inaktiv"
    assert se.call_args.args[1] is False
    ev = [e for e in _audit(dd) if e["event"] == "schalter_geaendert"]
    assert len(ev) == 1
    assert ev[0]["details"] == {"by": "verwalter1", "vorher": "aktiv", "nachher": "inaktiv"}


def test_post_fehler_409_mit_meldung_und_audit(client):
    c, dd = client
    with patch.object(schalter_api.trigger_state, "read_state", return_value=_st("aktiv")), \
         patch.object(schalter_api.trigger_state, "set_enabled",
                      side_effect=TriggerSchaltFehler("ORA-01031: insufficient privileges")):
        r = c.post("/api/schalter", json={"ein": False})
    assert r.status_code == 409 and "ORA-01031" in r.json()["detail"]
    ev = [e for e in _audit(dd) if e["event"] == "schalter_geaendert"]
    assert ev and "ORA-01031" in ev[0]["details"]["error"]


def test_post_ohne_bool_422(client):
    c, _ = client
    assert c.post("/api/schalter", json={"ein": "ja"}).status_code == 422
