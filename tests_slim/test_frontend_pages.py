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
