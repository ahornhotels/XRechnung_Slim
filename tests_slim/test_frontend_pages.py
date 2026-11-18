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


def test_einstellungen_info_knopf_mit_dialog():
    src = (FRONT / "settings.html").read_text(encoding="utf-8")
    assert 'class="info"' in src and "<dialog" in src and "showModal" in src
    assert "f.info" in src


def test_einstellungen_unbekannter_auswahlwert_bleibt_erhalten():
    """Ein Wert ausserhalb der Auswahl (z. B. alt 'auto') darf beim Speichern
    nicht still auf die erste Option springen."""
    src = (FRONT / "settings.html").read_text(encoding="utf-8")
    assert "f.choices.includes(f.value)" in src


# ── Menue, Schalter, neue Seiten ──

@pytest.mark.parametrize("page", ["archiv.html"])
def test_archivseite_vorhanden_und_login(page):
    src = (FRONT / page).read_text(encoding="utf-8")
    assert "401" in src and 'location.href = "/login"' in src


def test_routen_fuer_neue_seiten():
    import inspect
    import slim.main_slim as m
    src = inspect.getsource(m)
    for route in ('"/konfiguration"', '"/hoteldaten"', '"/system"', '"/archiv"', '"/nav.js"'):
        assert f"@app.get({route}" in src, route


def test_settings_leitet_auf_konfiguration():
    import inspect
    import slim.main_slim as m
    src = inspect.getsource(m.settings_page)
    assert 'RedirectResponse("/konfiguration"' in src


def test_nav_hat_alle_menuepunkte():
    src = (FRONT / "nav.js").read_text(encoding="utf-8")
    for txt in ("Übersicht", "Konfiguration XRechnung", "Hoteldaten", "Archiv", "System", "Benutzer",
                "/api/schalter", "/api/trigger-sql", "XRechnung EIN", "XRechnung AUS",
                "Trigger fehlt", "nicht prüfbar"):
        assert txt in src, txt


def test_nav_texte_schalter():
    src = (FRONT / "nav.js").read_text(encoding="utf-8")
    assert ("Neue Rechnungsmails gehen ohne XRechnung (nur PDF) raus. Bereits wartende Mails "
            "bleiben gesperrt, bis wieder eingeschaltet wird.") in src
    assert ("Neue Rechnungsmails werden wieder gesperrt und bekommen die XRechnung. Wartende Mails "
            "werden jetzt verarbeitet.") in src


@pytest.mark.parametrize("page", ["index.html", "settings.html", "archiv.html", "users.html"])
def test_alle_seiten_laden_nav(page):
    assert '<script src="/nav.js"></script>' in (FRONT / page).read_text(encoding="utf-8")


def test_startseite_ohne_archivkasten():
    src = (FRONT / "index.html").read_text(encoding="utf-8")
    assert 'id="archive_table"' not in src and 'href="/settings"' not in src


def test_settings_seite_nach_pfad():
    src = (FRONT / "settings.html").read_text(encoding="utf-8")
    for txt in ('"/konfiguration"', '"/hoteldaten"', '"/system"', "?page="):
        assert txt in src, txt


def test_archivseite_suche_und_ansicht():
    src = (FRONT / "archiv.html").read_text(encoding="utf-8")
    for txt in ("/api/archive", "/api/archive/ansicht", "/api/archive/file", 'id="q"', 'id="von"', 'id="bis"',
                "Rechnungsdatum", "unverändert"):
        assert txt in src, txt


def test_doku_nennt_schalter_und_bt10():
    root = FRONT.parent
    inst = (root / "INSTALL.md").read_text(encoding="utf-8")
    for txt in ("XRechnung EIN", "GRANT ALTER ANY TRIGGER", "Bearbeite gewähltes Fenster",
                "Konfiguration XRechnung", "Hoteldaten", "Archiv"):
        assert txt in inst, txt
    assert "Verarbeitung (Normalbetrieb oder Pause)" not in inst
    assert "bt10_freitext1" in (root / "README.md").read_text(encoding="utf-8")


def test_nav_nicht_pruefbar_mit_grant_zeigt_dialog():
    src = (FRONT / "nav.js").read_text(encoding="utf-8")
    assert "SYS.DBA_TRIGGERS" not in src           # Text kommt vom Server (grant_sql)
    assert 'zustand.state === "nicht_pruefbar" && !zustand.grant_sql' in src


def test_start_traegt_archiv_im_hintergrund_nach():
    import inspect
    import slim.main_slim as m
    assert "archive_fs.nachtragen" in inspect.getsource(m)
