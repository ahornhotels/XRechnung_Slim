"""Tests: Notfall-Zuruecksetzen eines Verwalters am Server (slim/scripts/reset_admin.py)."""
import json

import pytest

from slim.core_slim import auth
from slim.scripts import reset_admin as ra


def _store(tmp_path):
    return auth.UserStore(tmp_path / "users.json")


def test_vorhandener_verwalter_bekommt_startpasswort(tmp_path):
    s = _store(tmp_path)
    s.create("chef", "altes-passwort-1", "verwalten", must_change=False)
    s.create("leser", "leser-passwort-1", "ansehen")
    assert ra.reset_admin(s, "chef", "neues-passwort-1") == "zurueckgesetzt"
    u = s.get("chef")
    assert auth.verify_password("neues-passwort-1", u["hash"])
    assert u["must_change"] is True and u["role"] == "verwalten"
    assert s.get("leser")["role"] == "ansehen"      # andere unberuehrt


def test_ansehen_benutzer_wird_verwalter(tmp_path):
    s = _store(tmp_path)
    s.create("leser", "leser-passwort-1", "ansehen")
    assert ra.reset_admin(s, "leser", "neues-passwort-1") == "befoerdert"
    assert s.get("leser")["role"] == "verwalten"


def test_unbekannter_name_wird_angelegt(tmp_path):
    s = _store(tmp_path)
    assert ra.reset_admin(s, "neu", "neues-passwort-1") == "angelegt"
    u = s.get("neu")
    assert u["role"] == "verwalten" and u["must_change"] is True


def test_zu_kurzes_passwort_aendert_nichts(tmp_path):
    s = _store(tmp_path)
    s.create("chef", "altes-passwort-1", "verwalten", must_change=False)
    before = (tmp_path / "users.json").read_text(encoding="utf-8")
    with pytest.raises(auth.AuthError):
        ra.reset_admin(s, "chef", "kurz")
    assert (tmp_path / "users.json").read_text(encoding="utf-8") == before


def test_netzwerkpfad_wird_abgelehnt():
    assert ra.ist_netzwerkpfad(r"\\server\freigabe\XRechnung_Slim\slim")
    assert ra.ist_netzwerkpfad("//server/freigabe/slim")
    assert not ra.ist_netzwerkpfad(r"C:\FIDELIO\XRechnung_Slim\slim")


def test_main_lehnt_netzwerkpfad_ab(tmp_path, capsys):
    rc = ra.main(["chef"], slim_dir=r"\\server\freigabe\slim",
                 ask=lambda p: pytest.fail("darf nicht fragen"))
    assert rc == 5
    assert "nur am Server" in capsys.readouterr().out


def test_main_setzt_zurueck_und_protokolliert(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    auth.UserStore(data / "users.json").create("chef", "altes-passwort-1", "verwalten")
    answers = iter(["neues-passwort-1", "neues-passwort-1"])
    rc = ra.main(["chef"], slim_dir=tmp_path, ask=lambda p: next(answers))
    assert rc == 0
    u = auth.UserStore(data / "users.json").get("chef")
    assert auth.verify_password("neues-passwort-1", u["hash"])
    lines = [json.loads(l) for f in data.glob("audit-*.jsonl")
             for l in f.read_text(encoding="utf-8").splitlines()]
    ev = [e for e in lines if e.get("event") == "admin_zurueckgesetzt"]
    assert ev and ev[0]["details"]["user"] == "chef"
    assert "neues-passwort-1" not in json.dumps(lines)
    assert "neues-passwort-1" not in capsys.readouterr().out


def test_main_passwoerter_ungleich(tmp_path):
    (tmp_path / "data").mkdir()
    answers = iter(["neues-passwort-1", "anderes-passwort"])
    assert ra.main(["chef"], slim_dir=tmp_path, ask=lambda p: next(answers)) == 3
    assert not (tmp_path / "data" / "users.json").exists()


def test_main_kaputte_benutzerdatei(tmp_path, capsys):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "users.json").write_text("{kaputt", encoding="utf-8")
    answers = iter(["neues-passwort-1", "neues-passwort-1"])
    assert ra.main(["chef"], slim_dir=tmp_path, ask=lambda p: next(answers)) == 4
    assert "umbenennen" in capsys.readouterr().out
