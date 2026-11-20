"""Gescheiterte Mails stellen sich hinten an und blockieren neue nicht."""
from unittest.mock import MagicMock, patch

from modules import suite8_mailer
from slim.jobs_slim import poller


class _Cur:
    """Minimale WMAI: Zeilen (id, fehlertext); beantwortet die Abfragen von
    find_pending_wmai anhand von SQL-Text und Bindwerten."""

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
        self.out = [(r[0], "f.pdf", "s", "a@b") for r in rows[: binds["lim"]]]

    def fetchall(self):
        return self.out


def _conn(rows):
    conn = MagicMock()
    conn.cursor.return_value = _Cur(rows)
    return conn


def _ids(rows):
    return [r["wmai_id"] for r in rows]


def test_ohne_schalter_wie_bisher_nach_id():
    conn = _conn([(1, "x"), (2, None), (3, "x")])
    assert _ids(suite8_mailer.find_pending_wmai(conn, limit=2)) == [1, 2]


def test_neue_kommen_vor_gescheiterten():
    rows = [(i, "Fehler") for i in range(1, 11)] + [(11, None), (12, None)]
    out = suite8_mailer.find_pending_wmai(_conn(rows), limit=10, neue_zuerst=True)
    assert _ids(out)[:2] == [11, 12]
    assert [r["hatte_fehler"] for r in out] == [False, False] + [True] * 8


def test_gescheiterte_reihum():
    rows = [(i, "Fehler") for i in range(1, 6)]
    conn = _conn(rows)
    f = lambda nach: _ids(suite8_mailer.find_pending_wmai(
        conn, limit=2, neue_zuerst=True, nach_fehler_id=nach))
    assert f(0) == [1, 2]
    assert f(2) == [3, 4]
    assert f(4) == [5, 1]          # am Ende vorne weiter
    assert f(99) == [1, 2]


def test_wenige_gescheiterte_nicht_doppelt():
    conn = _conn([(1, "x"), (2, "x")])
    out = suite8_mailer.find_pending_wmai(conn, limit=10, neue_zuerst=True, nach_fehler_id=1)
    assert _ids(out) == [2, 1]


def test_volle_runde_neuer_mails_laesst_gescheiterte_warten():
    rows = [(1, "x")] + [(i, None) for i in range(2, 20)]
    out = suite8_mailer.find_pending_wmai(_conn(rows), limit=10, neue_zuerst=True)
    assert _ids(out) == list(range(2, 12))


def test_poller_merkt_sich_die_stelle(tmp_path):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock())
    cm.__exit__ = MagicMock(return_value=None)
    aufrufe = []

    def fake(conn, limit, neue_zuerst=False, nach_fehler_id=0):
        aufrufe.append((neue_zuerst, nach_fehler_id))
        return [{"wmai_id": 50, "filename": "", "subject": "", "to": "", "hatte_fehler": False},
                {"wmai_id": 7, "filename": "", "subject": "", "to": "", "hatte_fehler": True},
                {"wmai_id": 9, "filename": "", "subject": "", "to": "", "hatte_fehler": True}]

    hotel = {"mail_strategy": "suite8", "filename_pattern": "", "subject_pattern": r"Nr (?P<zinv_number>\d+)"}
    poller._fehler_cursor = 0
    with patch.object(poller, "load_hotel_config", return_value=hotel), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "_read_trigger_state", return_value="aktiv"), \
         patch.object(poller, "find_pending_wmai", side_effect=fake), \
         patch.object(poller, "_audit_fail_with_spam_guard", return_value=True):
        poller.run_once(data_dir=tmp_path)
        poller.run_once(data_dir=tmp_path)
    assert aufrufe == [(True, 0), (True, 9)]
