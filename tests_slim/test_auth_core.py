"""Tests: Benutzer, Passwort-Hash, Sitzungen, Sperre bei Fehlversuchen."""
import json

import pytest

from slim.core_slim import auth


def test_hash_kein_klartext_und_pruefung():
    h = auth.hash_password("geheimes-passwort")
    assert "geheimes-passwort" not in h and h.startswith("pbkdf2_sha256$")
    assert auth.verify_password("geheimes-passwort", h)
    assert not auth.verify_password("falsch-falsch", h)
    assert not auth.verify_password("x", "kaputt")


def test_userstore_anlegen_und_datei_ohne_klartext(tmp_path):
    s = auth.UserStore(tmp_path / "users.json")
    s.create("admin", "langes-passwort", "verwalten")
    raw = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert "langes-passwort" not in raw
    u = s.get("admin")
    assert u["role"] == "verwalten" and u["must_change"] is True
    assert s.count() == 1


def test_passwort_zu_kurz(tmp_path):
    s = auth.UserStore(tmp_path / "users.json")
    with pytest.raises(auth.AuthError):
        s.create("a", "kurz", "verwalten")


def test_rolle_und_name_gueltig(tmp_path):
    s = auth.UserStore(tmp_path / "users.json")
    with pytest.raises(auth.AuthError):
        s.create("a", "langes-passwort", "chef")
    s.create("a", "langes-passwort", "ansehen")
    with pytest.raises(auth.AuthError):
        s.create("a", "langes-passwort", "ansehen")   # doppelt


def test_letzter_verwalter_geschuetzt(tmp_path):
    s = auth.UserStore(tmp_path / "users.json")
    s.create("admin", "langes-passwort", "verwalten")
    s.create("leser", "langes-passwort", "ansehen")
    with pytest.raises(auth.AuthError):
        s.delete("admin")
    with pytest.raises(auth.AuthError):
        s.set_role("admin", "ansehen")
    s.create("chef2", "langes-passwort", "verwalten")
    s.delete("admin")
    assert s.get("admin") is None


def test_passwort_aendern(tmp_path):
    s = auth.UserStore(tmp_path / "users.json")
    s.create("admin", "langes-passwort", "verwalten")
    s.set_password("admin", "neues-langes-pw", must_change=False)
    assert auth.verify_password("neues-langes-pw", s.get("admin")["hash"])
    assert s.get("admin")["must_change"] is False


def test_sitzung_laeuft_ab():
    now = [1000.0]
    ss = auth.SessionStore(ttl_seconds=60, clock=lambda: now[0])
    t = ss.create("admin")
    assert ss.get(t)["user"] == "admin"
    now[0] += 50
    assert ss.get(t)                      # verlaengert
    now[0] += 50
    assert ss.get(t)                      # 50 s nach letzter Aktivitaet
    now[0] += 61
    assert ss.get(t) is None


def test_sitzungen_eines_benutzers_beenden():
    ss = auth.SessionStore()
    a, b = ss.create("x"), ss.create("y")
    ss.drop_user("x")
    assert ss.get(a) is None and ss.get(b)


def test_sperre_je_benutzer():
    now = [0.0]
    g = auth.LoginGuard(clock=lambda: now[0])
    for _ in range(5):
        g.fail("admin")
    assert g.blocked("admin") and not g.blocked("leser")
    now[0] += 15 * 60 + 1
    assert not g.blocked("admin")


def test_erfolg_setzt_zaehler_zurueck():
    g = auth.LoginGuard()
    for _ in range(4):
        g.fail("admin")
    g.ok("admin")
    for _ in range(4):
        g.fail("admin")
    assert not g.blocked("admin")


def test_kaputte_datei_wird_nicht_still_ueberschrieben(tmp_path):
    p = tmp_path / "users.json"
    p.write_text("{kaputt", encoding="utf-8")
    with pytest.raises(auth.AuthError):
        auth.UserStore(p).count()


def test_sperre_dauert_15_minuten_ab_fuenftem_fehlversuch():
    now = [0.0]
    g = auth.LoginGuard(clock=lambda: now[0])
    for t in (0, 1, 2, 3, 800):
        now[0] = t
        g.fail("k")
    now[0] = 800 + 14 * 60
    assert g.blocked("k")
    now[0] = 800 + 15 * 60 + 1
    assert not g.blocked("k")


def test_sperrliste_waechst_nicht_unbegrenzt():
    g = auth.LoginGuard(max_keys=100)
    for i in range(1000):
        g.fail(f"name{i}")
    assert len(g._fails) <= 100


def test_aktive_sperre_wird_nicht_verdraengt():
    g = auth.LoginGuard(max_keys=10)
    for _ in range(5):
        g.fail("opfer")
    for i in range(50):
        for _ in range(5):
            g.fail(f"spray{i}")
    assert g.blocked("opfer")


def test_schnelle_schreibfolge_liefert_aktuellen_stand(tmp_path):
    s = auth.UserStore(tmp_path / "users.json")
    s.create("admin", "langes-passwort", "verwalten")
    for i in range(20):
        s.create(f"u{i}", "langes-passwort", "ansehen")
        s.set_role(f"u{i}", "verwalten")
        assert s.get(f"u{i}")["role"] == "verwalten"



def test_sperrliste_hart_begrenzt():
    g = auth.LoginGuard(max_keys=2)
    for i in range(100):
        for _ in range(5):
            g.fail(f"k{i}")
    assert len(g._until) <= 20
