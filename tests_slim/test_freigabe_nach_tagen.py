"""Tests: Gesperrte Rechnungsmails nach X Tagen (Hoteldatum) ohne XRechnung freigeben."""
import datetime as dt
import json
from unittest.mock import MagicMock, patch

import pytest

from modules import suite8_mailer
from slim.core_slim import settings_schema
from slim.jobs_slim import poller


# ── Datenbank: release_overdue_wmai ──

class _Cur:
    def __init__(self, rows, rowcounts):
        self.rows, self.rowcounts, self.calls = rows, list(rowcounts), []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))
        if sql.strip().upper().startswith("UPDATE"):
            self.rowcount = self.rowcounts.pop(0)

    def fetchall(self):
        return self.rows


def _conn(cur):
    c = MagicMock()
    c.cursor.return_value = cur
    return c


def test_freigabe_waehlt_nach_hoteldatum_und_entsperrt():
    d = dt.datetime(2026, 11, 10)
    cur = _Cur([(11, "Folio_1.pdf", "Rechnung Nr. 900001", d, "kosit_fail"),
                (12, "Folio_2.pdf", "Rechnung Nr. 900002", d, None)], [1, 1])
    conn = _conn(cur)
    out = suite8_mailer.release_overdue_wmai(conn, 3)
    sel_sql, sel_params = cur.calls[0]
    assert "WMAI_BLOCKSEND=1" in sel_sql and "WMAI_SENT=0" in sel_sql
    # Hoteldatum aus WGBS, Fenster [X, X+7] Tage - wie die manuelle Freigabe
    assert "WMAI_FIDELIODATE >= (SELECT MAX(TRUNC(WGBS_DATEVALUE)) FROM WGBS) - :bis" in sel_sql
    assert "WMAI_FIDELIODATE < (SELECT MAX(TRUNC(WGBS_DATEVALUE)) FROM WGBS) - :tage + 1" in sel_sql
    assert "SYSDATE" not in sel_sql
    assert sel_params["tage"] == 3 and sel_params["bis"] == 10
    upd = [c for c in cur.calls if c[0].upper().startswith("UPDATE")]
    assert len(upd) == 2
    assert "SET WMAI_BLOCKSEND=0" in upd[0][0]
    assert "WMAI_BLOCKSEND=1" in upd[0][0] and "WMAI_SENT=0" in upd[0][0]   # nur noch Gesperrte
    assert upd[0][1] == {"id": 11}
    conn.commit.assert_called()
    assert [r["wmai_id"] for r in out] == [11, 12]
    assert out[0]["fideliodate"] == "2026-11-10" and out[0]["error"] == "kosit_fail"


def test_freigabe_meldet_nur_wirklich_entsperrte():
    d = dt.datetime(2026, 11, 10)
    cur = _Cur([(11, "", "", d, None), (12, "", "", d, None)], [0, 1])   # 11 inzwischen erledigt
    assert [r["wmai_id"] for r in suite8_mailer.release_overdue_wmai(_conn(cur), 3)] == [12]


@pytest.mark.parametrize("tage", [0, -1, None])
def test_freigabe_aus_fragt_db_nicht(tage):
    conn = MagicMock()
    assert suite8_mailer.release_overdue_wmai(conn, tage) == []
    conn.cursor.assert_not_called()


# ── Poller ──

def _cfg(tage):
    c = {"mail_strategy": "suite8", "suite8_recognize_filename_pattern": "",
         "suite8_recognize_subject_pattern": r"Rechnung Nr\.?\s*(?P<zinv_number>\d+)",
         "suite8_attachment_name_template": "{zinv_number}.xml"}
    if tage is not None:
        c["freigabe_nach_tagen"] = tage
    return c


def _cm():
    conn = MagicMock(name="conn")
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=None)
    return cm


@pytest.fixture(autouse=True)
def _reset():
    poller._letzter_trigger_state = None
    yield
    poller._letzter_trigger_state = None


def _run(tmp_path, tage, state="aktiv", released=None, release_exc=None):
    rel = MagicMock(return_value=released or [], side_effect=release_exc)
    with patch.object(poller, "load_hotel_config", return_value=_cfg(tage)), \
         patch.object(poller, "get_connection", return_value=_cm()), \
         patch.object(poller.trigger_state, "read_state",
                      return_value={"state": state, "owner": "X", "user": "X", "grant_sql": None, "error": None}), \
         patch.object(poller, "find_pending_wmai", return_value=[]), \
         patch.object(poller, "release_overdue_wmai", rel):
        s = poller.run_once(data_dir=tmp_path)
    return s, rel


def _events(tmp_path, name):
    out = []
    for f in tmp_path.glob("audit-*.jsonl"):
        out += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [e for e in out if e["event"] == name]


def test_poller_gibt_ueberfaellige_frei_und_protokolliert(tmp_path):
    rows = [{"wmai_id": 11, "filename": "", "subject": "Rechnung Nr. 900001",
             "fideliodate": "2026-11-10", "error": "kosit_fail: x"}]
    s, rel = _run(tmp_path, 3, released=rows)
    rel.assert_called_once()
    assert rel.call_args.args[1] == 3
    assert s["freigegeben"] == 1
    ev = _events(tmp_path, "freigegeben_ohne_xrechnung")
    assert len(ev) == 1 and ev[0]["wmai_id"] == 11 and ev[0]["zinv_number"] == "900001"
    assert ev[0]["details"]["tage"] == 3 and ev[0]["details"]["hoteldatum"] == "2026-11-10"
    assert ev[0]["details"]["letzter_fehler"] == "kosit_fail: x"


@pytest.mark.parametrize("tage", [None, 0])
def test_poller_ohne_einstellung_gibt_nichts_frei(tmp_path, tage):
    s, rel = _run(tmp_path, tage)
    rel.assert_not_called()
    assert s.get("freigegeben", 0) == 0


def test_poller_bei_schalter_aus_gibt_nichts_frei(tmp_path):
    s, rel = _run(tmp_path, 3, state="inaktiv")
    rel.assert_not_called()


def test_poller_freigabe_fehler_crasht_nicht(tmp_path):
    s, rel = _run(tmp_path, 3, release_exc=RuntimeError("ORA-01031"))
    assert s["db_error"] is True
    ev = _events(tmp_path, "poller_db_error")
    assert ev and ev[0]["details"]["phase"] == "freigabe"


# ── Einstellung ──

def test_einstellung_freigabe_nach_tagen():
    s = {x.key: x for sec in settings_schema.SECTIONS for x in sec.settings}["freigabe_nach_tagen"]
    sec = next(sec for sec in settings_schema.SECTIONS if s in sec.settings)
    assert sec.page == "xrechnung"
    assert s.type == "int" and s.minimum == 0 and s.maximum == 365 and s.default == 0
