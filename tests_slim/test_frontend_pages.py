"""Tests: Seiten der Oberflaeche werden ausgeliefert und leiten bei 401 auf /login."""
from pathlib import Path

import pytest

FRONT = Path(__file__).resolve().parent.parent / "slim" / "frontend"


@pytest.mark.parametrize("page", ["login.html", "users.html", "settings.html", "index.html"])
def test_seite_vorhanden(page):
    assert (FRONT / page).exists()


@pytest.mark.parametrize("page", ["users.html", "settings.html", "index.html"])
def test_seite_leitet_bei_401_auf_login(page):
    src = (FRONT / page).read_text(encoding="utf-8")
    assert "401" in src and 'location.href = "/login"' in src


def test_einstellungsseite_zeigt_geheimnisse_nicht():
    src = (FRONT / "settings.html").read_text(encoding="utf-8")
    assert 'type="password"' in src and "leer lassen = unverändert" in src


def test_routen_fuer_seiten():
    import inspect
    import slim.main_slim as m
    src = inspect.getsource(m)
    for route in ('"/login"', '"/users"', '"/settings"'):
        assert f"@app.get({route})" in src



def test_login_bei_neueinrichtung_mit_benutzern():
    """Marker geloescht, Benutzer vorhanden: Anmeldeformular statt Sackgasse."""
    src = (FRONT / "login.html").read_text(encoding="utf-8")
    assert "!s.setup_done && !s.users_exist" in src



def test_login_leitet_nur_verwalter_zum_wizard():
    src = (FRONT / "login.html").read_text(encoding="utf-8")
    assert 's.role === "verwalten" ? "/setup" : "/"' in src


def test_startseite_erkennt_alten_dienst_nach_update():
    """Update eingespielt, Dienst aber nicht neu gestartet: der alte Dienst kennt
    /api/auth/state nicht (404). Dann nicht nach /login (ebenfalls 404 ->
    {"detail":"Not Found"}) weiterleiten, sondern einen Hinweis zeigen."""
    src = (FRONT / "index.html").read_text(encoding="utf-8")
    assert "r.status === 404" in src
    assert "noch mit der alten Version" in src
    assert 'getElementById("restart_banner").innerHTML' in src   # eigenes Element, checkUpdate leert update_banner


def test_nach_update_warten_bis_neue_version_antwortet():
    """Kein fester 10-s-Reload: warten, bis /healthz die neue Version meldet;
    bleibt der Neustart aus, klarer Hinweis statt Fehlerseite."""
    src = (FRONT / "index.html").read_text(encoding="utf-8")
    assert "location.reload(); }, 10000)" not in src
    assert "h.version === want" in src
    assert "nicht neu gestartet" in src


def test_einstellungen_neustart_wartet_auf_dienst():
    src = (FRONT / "settings.html").read_text(encoding="utf-8")
    assert "setTimeout(() => location.reload(), 15000)" not in src
    assert "/healthz" in src


def test_healthz_meldet_startzeitpunkt():
    from fastapi.testclient import TestClient
    from slim import main_slim
    j = TestClient(main_slim.app).get("/healthz").json()
    assert j["ok"] is True and j.get("started")


def test_einstellungen_erkennt_neustart_am_startzeitpunkt():
    src = (FRONT / "settings.html").read_text(encoding="utf-8")
    assert "h.started !== before" in src
