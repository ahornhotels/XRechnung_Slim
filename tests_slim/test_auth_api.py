"""Tests: Anmeldung im Server (Middleware, Rollen, Ersteinrichtung)."""
import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from slim.api_slim import auth_api
from slim.core_slim import auth


@pytest.fixture
def setup(tmp_path, monkeypatch):
    users = auth.UserStore(tmp_path / "users.json")
    monkeypatch.setattr(auth_api, "USERS", users)
    monkeypatch.setattr(auth_api, "SESSIONS", auth.SessionStore())
    monkeypatch.setattr(auth_api, "GUARD", auth.LoginGuard())
    monkeypatch.setattr(auth_api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(auth_api, "_is_local", lambda request: False)
    monkeypatch.setattr(auth_api, "_setup_done", lambda: True)
    app = FastAPI()
    app.middleware("http")(auth_api.middleware)
    app.include_router(auth_api.router)

    @app.get("/api/status")
    def status():
        return {"ok": True}

    @app.post("/api/poller/run-now")
    def run_now():
        return {"ok": True}

    @app.get("/api/sql/templates")
    def sql():
        return {"ok": True}

    @app.get("/")
    def index():
        return PlainTextResponse("index")

    @app.get("/healthz")
    def health():
        return {"ok": True}

    return TestClient(app), users, monkeypatch


def _login(client, name, pw):
    return client.post("/api/auth/login", json={"username": name, "password": pw})


def test_ohne_sitzung_401_und_umleitung(setup):
    client, users, _ = setup
    users.create("admin", "langes-passwort", "verwalten", must_change=False)
    assert client.get("/api/status").status_code == 401
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 303, 307) and r.headers["location"].startswith("/login")
    assert client.get("/healthz").status_code == 200


def test_login_und_cookie_eigenschaften(setup):
    client, users, _ = setup
    users.create("admin", "langes-passwort", "verwalten", must_change=False)
    r = _login(client, "admin", "langes-passwort")
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/status").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/status").status_code == 401


def test_ansehen_darf_lesen_nicht_schreiben(setup):
    client, users, _ = setup
    users.create("admin", "langes-passwort", "verwalten", must_change=False)
    users.create("leser", "langes-passwort", "ansehen", must_change=False)
    _login(client, "leser", "langes-passwort")
    assert client.get("/api/status").status_code == 200
    assert client.post("/api/poller/run-now").status_code == 403
    assert client.get("/api/sql/templates").status_code == 403


def test_verwalten_darf_alles(setup):
    client, users, _ = setup
    users.create("admin", "langes-passwort", "verwalten", must_change=False)
    _login(client, "admin", "langes-passwort")
    assert client.post("/api/poller/run-now").status_code == 200
    assert client.get("/api/sql/templates").status_code == 200


def test_falsches_passwort_neutral_und_sperre(setup):
    client, users, _ = setup
    users.create("admin", "langes-passwort", "verwalten", must_change=False)
    for _ in range(5):
        r = _login(client, "admin", "falsches-passwort")
        assert r.status_code == 401 and r.json()["detail"] == "Anmeldung fehlgeschlagen"
    assert _login(client, "admin", "langes-passwort").status_code == 401   # gesperrt
    assert _login(client, "niemand", "egal-egal-egal").json()["detail"] == "Anmeldung fehlgeschlagen"


def test_must_change_erzwingt_passwortwechsel(setup):
    client, users, _ = setup
    users.create("admin", "langes-passwort", "verwalten", must_change=True)
    _login(client, "admin", "langes-passwort")
    assert client.get("/api/status").status_code == 403
    r = client.post("/api/auth/password", json={"old": "langes-passwort", "new": "noch-laengeres-pw"})
    assert r.status_code == 200
    assert client.get("/api/status").status_code == 200


def test_bootstrap_nur_lokal_und_nur_ohne_benutzer(setup):
    client, users, mp = setup
    assert client.post("/api/auth/bootstrap", json={"username": "admin", "password": "langes-passwort"}).status_code == 403
    mp.setattr(auth_api, "_is_local", lambda request: True)
    assert client.get("/api/auth/state").json()["users_exist"] is False
    r = client.post("/api/auth/bootstrap", json={"username": "admin", "password": "langes-passwort"})
    assert r.status_code == 200 and users.get("admin")["role"] == "verwalten"
    assert client.post("/api/auth/bootstrap", json={"username": "x", "password": "langes-passwort"}).status_code == 403


def test_ohne_benutzer_api_gesperrt(setup):
    client, _, _ = setup
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/auth/state").status_code == 200


def test_login_wird_auditiert_ohne_passwort(setup, tmp_path):
    client, users, _ = setup
    users.create("admin", "langes-passwort", "verwalten", must_change=False)
    _login(client, "admin", "falsches-passwort")
    _login(client, "admin", "langes-passwort")
    text = "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("audit-*.jsonl"))
    assert "login_failed" in text and "login_ok" in text and "passwort" not in text


def test_vor_der_einrichtung_fuehrt_wurzel_zum_wizard(setup):
    client, _, mp = setup
    mp.setattr(auth_api, "_setup_done", lambda: False)
    assert client.get("/", follow_redirects=False).status_code == 200   # Route leitet selbst auf /setup


def test_main_app_bindet_anmeldung_ein():
    import inspect
    import slim.main_slim as m
    src = inspect.getsource(m)
    assert src.index("auth_api_module.middleware") < src.index("async def _ip_allowlist")
    assert '@app.get("/login")' in src
