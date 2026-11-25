"""Tests: Mails, die nicht die XRechnung gesperrt hat, bleiben unangetastet.

Befund aus dem Feld (25.11.2026): Suite8 setzt WMAI_BLOCKSEND=1 selten auch
selbst, ohne den XRechnung-Trigger - bisher nur bei Reservierungskorrespondenz.
Slim hat solche Mails wie Rechnungsmails behandelt: Fehlertext an die Mail
geschrieben und sie gesperrt gelassen.

Regel: Slim gehoert nur, was auf das Erkennungsmuster passt (dasselbe Muster
wie im Trigger). Alles andere ist eine fremde Sperre: nicht verarbeiten, nicht
beschriften, nicht nach X Tagen freigeben. Ein Verwalter kann sie von Hand
freigeben.
"""
import datetime as dt
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules import suite8_mailer, suite8_pattern
from slim.api_slim import retry as retry_api
from slim.api_slim import status as status_api
from slim.jobs_slim import poller

SUB = r"Ihre\s+Rechnung\s+#\s*(?P<zinv_number>\d+)"
RECHNUNG = "Ihre Rechnung # 900001"
BESTAETIGUNG = "Reservierungsbestätigung Nr. 876694"


def _ist(subject, filename="", fn_pat="", sub_pat=SUB):
    return suite8_pattern.ist_rechnungsmail(filename=filename, subject=subject,
                                            filename_pattern=fn_pat, subject_pattern=sub_pat)


# ── Erkennung ──

def test_rechnungsmail_wird_erkannt():
    assert _ist(RECHNUNG) is True


def test_reservierungsbestaetigung_ist_keine_rechnungsmail():
    assert _ist(BESTAETIGUNG) is False


def test_dateiname_reicht_fuer_rechnungsmail():
    assert _ist(BESTAETIGUNG, filename="Folio_4711.pdf",
                fn_pat=r"Folio_(?P<zinv_id>\d+)\.pdf", sub_pat="") is True


def test_kaputtes_muster_gilt_nicht_als_fremd():
    # Sonst wuerde ein Tippfehler im Muster alle Rechnungsmails still liegen lassen.
    assert _ist(RECHNUNG, sub_pat=r"Rechnung (\d+)") is True      # ohne Named-Group
    assert _ist(RECHNUNG, sub_pat=r"Rechnung (?P<zinv_number>\d+") is True  # Syntaxfehler
    assert _ist(RECHNUNG, sub_pat="") is True                      # kein Muster


# ── Poller-Auswahl: find_pending_wmai(nur=...) ──

class _Cur:
    """WMAI-Zeilen (id, fehlertext, betreff)."""

    def __init__(self, rows):
        self.rows, self.out = sorted(rows), []

    def execute(self, sql, binds=None):
        s = " ".join(sql.upper().split())
        rows = self.rows
        if "WMAI_ERROR IS NULL" in s:
            rows = [r for r in rows if r[1] is None]
        elif "WMAI_ERROR IS NOT NULL" in s:
            rows = [r for r in rows if r[1] is not None]
        if "WMAI_ID > :NACH" in s:
            rows = [r for r in rows if r[0] > binds["nach"]]
        elif "WMAI_ID <= :NACH" in s:
            rows = [r for r in rows if r[0] <= binds["nach"]]
        self.out = [(r[0], "", r[2], "a@b") for r in rows[: binds["lim"]]]

    def fetchall(self):
        return self.out


def _conn(rows):
    conn = MagicMock()
    conn.cursor.return_value = _Cur(rows)
    return conn


def _nur(row):
    return _ist(row["subject"])


def test_fremde_sperren_belegen_keine_plaetze():
    # Zwoelf alte Bestaetigungen duerfen zwei neue Rechnungen nicht verdraengen.
    rows = [(i, None, BESTAETIGUNG) for i in range(1, 13)] + [(13, None, RECHNUNG), (14, None, RECHNUNG)]
    out = suite8_mailer.find_pending_wmai(_conn(rows), limit=10, neue_zuerst=True, nur=_nur)
    assert [r["wmai_id"] for r in out] == [13, 14]


def test_fremde_sperre_mit_altem_fehlertext_bleibt_auch_draussen():
    rows = [(1, "Kein Pattern hat getroffen", BESTAETIGUNG), (2, "kosit_fail", RECHNUNG)]
    out = suite8_mailer.find_pending_wmai(_conn(rows), limit=10, neue_zuerst=True, nur=_nur)
    assert [r["wmai_id"] for r in out] == [2]


def test_ohne_filter_wie_bisher():
    rows = [(1, None, BESTAETIGUNG), (2, None, RECHNUNG)]
    assert [r["wmai_id"] for r in suite8_mailer.find_pending_wmai(_conn(rows), limit=10)] == [1, 2]


def test_poller_laesst_fremde_sperre_unangetastet(tmp_path):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock())
    cm.__exit__ = MagicMock(return_value=None)
    gesehen = {}

    def fake(conn, limit, neue_zuerst=False, nach_fehler_id=0, nur=None):
        gesehen["nur"] = nur
        return []

    hotel = {"mail_strategy": "suite8", "suite8_recognize_subject_pattern": SUB}
    with patch.object(poller, "load_hotel_config", return_value=hotel), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "_read_trigger_state", return_value="aktiv"), \
         patch.object(poller, "find_pending_wmai", side_effect=fake), \
         patch.object(poller, "_audit_fail_with_spam_guard") as fehler:
        poller.run_once(data_dir=tmp_path)
    assert gesehen["nur"]({"filename": "", "subject": BESTAETIGUNG}) is False
    assert gesehen["nur"]({"filename": "", "subject": RECHNUNG}) is True
    fehler.assert_not_called()


# ── Freigabe nach X Tagen ──

class _FCur:
    def __init__(self, rows):
        self.rows, self.calls, self.rowcount = rows, [], 0

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))
        if sql.strip().upper().startswith("UPDATE"):
            self.rowcount = 1

    def fetchall(self):
        return self.rows


def test_freigabe_nach_tagen_gibt_keine_fremde_sperre_frei():
    d = dt.datetime(2026, 11, 20)
    cur = _FCur([(11, "", BESTAETIGUNG, d, None), (12, "", RECHNUNG, d, "kosit_fail")])
    conn = MagicMock()
    conn.cursor.return_value = cur
    out = suite8_mailer.release_overdue_wmai(conn, 3, nur=_nur)
    assert [r["wmai_id"] for r in out] == [12]
    upd = [c for c in cur.calls if c[0].upper().startswith("UPDATE")]
    assert [c[1] for c in upd] == [{"id": 12}]


# ── Oberflaeche: Kennzeichnung und Freigabe von Hand ──

@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(retry_api.router)
    app.include_router(status_api.router)
    status_api.get_state().update({"data_dir": tmp_path, "interval_seconds": 30,
                                   "last_run": None, "last_run_summary": None})
    return TestClient(app), tmp_path


def _cm():
    conn = MagicMock(name="conn")
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=None)
    return cm


HOTEL = {"suite8_recognize_subject_pattern": SUB}


def test_pending_kennzeichnet_fremde_sperre(client):
    c, _ = client
    rows = [{"wmai_id": 1, "filename": "", "subject": BESTAETIGUNG, "to": "x"},
            {"wmai_id": 2, "filename": "", "subject": RECHNUNG, "to": "y"}]
    with patch.object(status_api, "get_connection", return_value=_cm()), \
         patch.object(status_api, "find_pending_wmai", return_value=rows), \
         patch.object(status_api, "get_wmai_error", return_value=None), \
         patch.object(status_api, "load_hotel_config", return_value=HOTEL):
        items = c.get("/api/pending").json()["items"]
    assert [(i["wmai_id"], i["fremd"]) for i in items] == [(1, True), (2, False)]


def test_fremde_sperre_von_hand_freigeben(client):
    c, dd = client
    mail = {"wmai_id": 1, "filename": "", "subject": BESTAETIGUNG, "to": "x",
            "fideliodate": "2026-11-23"}
    with patch.object(retry_api, "get_connection", return_value=_cm()), \
         patch.object(retry_api, "load_hotel_config", return_value=HOTEL), \
         patch.object(retry_api, "get_blocked_wmai", return_value=mail), \
         patch.object(retry_api, "release_wmai", return_value=True) as frei:
        r = c.post("/api/wmai/1/freigeben")
    assert r.status_code == 200 and r.json()["ok"] is True
    frei.assert_called_once()
    protokoll = (dd / "audit.jsonl").read_text(encoding="utf-8") if (dd / "audit.jsonl").exists() \
        else "".join(p.read_text(encoding="utf-8") for p in dd.glob("*.jsonl"))
    assert "fremde_sperre_freigegeben" in protokoll and "2026-11-23" in protokoll


def test_rechnungsmail_laesst_sich_so_nicht_freigeben(client):
    c, _ = client
    mail = {"wmai_id": 2, "filename": "", "subject": RECHNUNG, "to": "y", "fideliodate": "2026-11-23"}
    with patch.object(retry_api, "get_connection", return_value=_cm()), \
         patch.object(retry_api, "load_hotel_config", return_value=HOTEL), \
         patch.object(retry_api, "get_blocked_wmai", return_value=mail), \
         patch.object(retry_api, "release_wmai") as frei:
        r = c.post("/api/wmai/2/freigeben")
    assert r.status_code == 409
    frei.assert_not_called()


def test_freigeben_einer_nicht_gesperrten_mail_meldet_404(client):
    c, _ = client
    with patch.object(retry_api, "get_connection", return_value=_cm()), \
         patch.object(retry_api, "load_hotel_config", return_value=HOTEL), \
         patch.object(retry_api, "get_blocked_wmai", return_value=None), \
         patch.object(retry_api, "release_wmai") as frei:
        r = c.post("/api/wmai/9/freigeben")
    assert r.status_code == 404
    frei.assert_not_called()


def test_release_wmai_entsperrt_nur_gesperrte_ungesendete():
    cur = _FCur([])
    conn = MagicMock()
    conn.cursor.return_value = cur
    assert suite8_mailer.release_wmai(conn, 7) is True
    sql, params = cur.calls[0]
    assert "SET WMAI_BLOCKSEND=0" in sql and "WMAI_BLOCKSEND=1" in sql and "WMAI_SENT=0" in sql
    assert params == {"id": 7}
    conn.commit.assert_called()
