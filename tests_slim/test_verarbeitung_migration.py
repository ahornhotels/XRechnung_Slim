"""Tests: Altwert mail_strategy='aus' (alte Einstellung "Verarbeitung") wird in
den XRechnung-Schalter ueberfuehrt - sonst bliebe Slim nach dem Update stumm,
waehrend der Schalter "EIN" zeigt."""
import json
from unittest.mock import MagicMock, patch

import pytest

from slim.core_slim import verarbeitung
from slim.jobs_slim import poller


@pytest.fixture
def hotel(tmp_path, monkeypatch):
    p = tmp_path / "hotel.json"
    monkeypatch.setattr(verarbeitung, "_hotel_path", lambda: p)

    def write(d):
        p.write_text(json.dumps(d), encoding="utf-8")
    return p, write


def _st(s):
    return {"state": s, "owner": "V8LIVE", "user": "V8LIVE", "grant_sql": None, "error": None}


def test_aus_aufheben_setzt_suite8_und_behaelt_rest(hotel):
    p, write = hotel
    write({"mail_strategy": "aus", "hotel_code": "X"})
    assert verarbeitung.aus_aufheben() is True
    assert json.loads(p.read_text(encoding="utf-8")) == {"mail_strategy": "suite8", "hotel_code": "X"}


def test_aus_aufheben_laesst_andere_werte(hotel):
    p, write = hotel
    write({"mail_strategy": "graph"})
    assert verarbeitung.aus_aufheben() is False
    assert json.loads(p.read_text(encoding="utf-8"))["mail_strategy"] == "graph"


def test_migration_schaltet_trigger_aus_und_hebt_auf(hotel):
    p, write = hotel
    write({"mail_strategy": "aus"})
    with patch.object(verarbeitung.trigger_state, "read_state", return_value=_st("aktiv")), \
         patch.object(verarbeitung.trigger_state, "set_enabled", return_value=_st("inaktiv")) as se:
        assert verarbeitung.migriere_aus(MagicMock()) is True
    assert se.call_args.args[1] is False
    assert json.loads(p.read_text(encoding="utf-8"))["mail_strategy"] == "suite8"


def test_migration_trigger_schon_inaktiv(hotel):
    p, write = hotel
    write({"mail_strategy": "aus"})
    with patch.object(verarbeitung.trigger_state, "read_state", return_value=_st("inaktiv")), \
         patch.object(verarbeitung.trigger_state, "set_enabled") as se:
        assert verarbeitung.migriere_aus(MagicMock()) is True
    se.assert_not_called()
    assert json.loads(p.read_text(encoding="utf-8"))["mail_strategy"] == "suite8"


@pytest.mark.parametrize("state", ["fehlt", "nicht_pruefbar"])
def test_migration_ohne_schaltbaren_trigger_bleibt_aus(hotel, state):
    p, write = hotel
    write({"mail_strategy": "aus"})
    with patch.object(verarbeitung.trigger_state, "read_state", return_value=_st(state)):
        assert verarbeitung.migriere_aus(MagicMock()) is False
    assert json.loads(p.read_text(encoding="utf-8"))["mail_strategy"] == "aus"


def test_migration_schaltfehler_bleibt_aus(hotel):
    p, write = hotel
    write({"mail_strategy": "aus"})
    with patch.object(verarbeitung.trigger_state, "read_state", return_value=_st("aktiv")), \
         patch.object(verarbeitung.trigger_state, "set_enabled",
                      side_effect=verarbeitung.trigger_state.TriggerSchaltFehler("ORA-01031")):
        assert verarbeitung.migriere_aus(MagicMock()) is False
    assert json.loads(p.read_text(encoding="utf-8"))["mail_strategy"] == "aus"


def test_poller_migriert_aus_vor_der_strategiepruefung(tmp_path):
    cfgs = [{"mail_strategy": "aus"}, {"mail_strategy": "suite8", "suite8_recognize_subject_pattern": "x"}]
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock())
    cm.__exit__ = MagicMock(return_value=None)
    with patch.object(poller, "load_hotel_config", side_effect=lambda: cfgs.pop(0)), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller.verarbeitung, "migriere_aus", return_value=True) as mig, \
         patch.object(poller.trigger_state, "read_state", return_value=_st("inaktiv")):
        s = poller.run_once(data_dir=tmp_path)
    mig.assert_called_once()
    assert s["skipped_strategy"] is False and s["skipped_trigger"] is True
