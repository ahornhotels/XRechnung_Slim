"""Tests: Zustand des Suite8-Triggers WMAI_XRECHNUNG_BLOCK lesen und schalten."""
import pytest

from slim.core_slim import trigger_state
from slim.core_slim.trigger_state import TriggerSchaltFehler, read_state, set_enabled


class _Cur:
    """Antwortet je nach SQL-Teilstring; merkt sich alle Befehle."""

    def __init__(self, user="V8LIVE", tables=("V8LIVE",), synonym=None, trig=None, error=None):
        self.user, self.tables, self.synonym, self.trig, self.error = user, tables, synonym, trig, error
        self.calls = []
        self._rows = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split()).lower()
        self.calls.append((s, params))
        if self.error:
            raise self.error
        if "from dual" in s:
            self._rows = [(self.user,)]
        elif "all_tables" in s:
            self._rows = [(o,) for o in self.tables]
        elif "all_synonyms" in s:
            self._rows = [(self.synonym,)] if self.synonym else []
        elif "all_triggers" in s:
            self._rows = [self.trig] if self.trig else []
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur


def _c(**kw):
    return _Conn(_Cur(**kw))


def test_triggername():
    assert trigger_state.TRIGGER_NAME == "WMAI_XRECHNUNG_BLOCK"


def test_aktiv_eigener_trigger():
    st = read_state(_c(trig=("V8LIVE", "ENABLED")))
    assert st["state"] == "aktiv" and st["owner"] == "V8LIVE" and st["grant_sql"] is None


def test_inaktiv():
    assert read_state(_c(trig=("V8LIVE", "DISABLED")))["state"] == "inaktiv"


def test_fehlt_nur_wenn_eigene_tabelle():
    assert read_state(_c(trig=None))["state"] == "fehlt"


def test_fremde_tabelle_ohne_sicht_ist_nicht_pruefbar():
    class _Blind(_Cur):
        def execute(self, sql, params=None):
            if "dba_triggers" in sql.lower():
                raise RuntimeError("ORA-00942")
            return super().execute(sql, params)
    st = read_state(_Conn(_Blind(user="SLIM", tables=(), synonym="V8LIVE", trig=None)))
    assert st["state"] == "nicht_pruefbar"


def test_trigger_abfrage_auf_tabellenbesitzer():
    conn = _c(user="SLIM", tables=(), synonym="V8LIVE", trig=("V8LIVE", "ENABLED"))
    read_state(conn)
    sql, params = next(c for c in conn.cur.calls if "all_triggers" in c[0])
    assert params["n"] == "WMAI_XRECHNUNG_BLOCK" and params["o"] == "V8LIVE"


def test_fremder_trigger_liefert_grant():
    st = read_state(_c(user="SLIM", tables=(), synonym="V8LIVE", trig=("V8LIVE", "ENABLED")))
    assert st["state"] == "aktiv"
    assert st["grant_sql"] == "GRANT ALTER ANY TRIGGER TO SLIM;"


def test_db_fehler_ist_nicht_pruefbar():
    st = read_state(_c(error=RuntimeError("ORA-03113 Verbindung weg")))
    assert st["state"] == "nicht_pruefbar" and "ORA-03113" in st["error"]


def test_schalten_sql():
    conn = _c(trig=("V8LIVE", "ENABLED"))
    set_enabled(conn, False)
    alters = [c[0] for c in conn.cur.calls if c[0].startswith("alter trigger")]
    assert alters == ['alter trigger "v8live"."wmai_xrechnung_block" disable']


def test_einschalten_sql():
    conn = _c(trig=("V8LIVE", "DISABLED"))
    set_enabled(conn, True)
    assert any(c[0].endswith(" enable") for c in conn.cur.calls if c[0].startswith("alter trigger"))


def test_schalten_fehlt_wirft():
    conn = _c(trig=None)
    with pytest.raises(TriggerSchaltFehler):
        set_enabled(conn, False)
    assert not any(c[0].startswith("alter") for c in conn.cur.calls)


def test_besitzer_mit_sonderzeichen_wird_abgelehnt():
    conn = _c(trig=('X"; DROP', "ENABLED"))
    with pytest.raises(TriggerSchaltFehler):
        set_enabled(conn, False)
    assert not any(c[0].startswith("alter") for c in conn.cur.calls)


def test_oracle_fehler_beim_schalten():
    class _Cur2(_Cur):
        def execute(self, sql, params=None):
            if sql.strip().upper().startswith("ALTER"):
                raise RuntimeError("ORA-01031: insufficient privileges")
            return super().execute(sql, params)
    conn = _Conn(_Cur2(trig=("V8LIVE", "ENABLED")))
    with pytest.raises(TriggerSchaltFehler) as e:
        set_enabled(conn, False)
    assert "ORA-01031" in str(e.value)


# ── Trigger gehoert einem anderen Benutzer und ist in ALL_TRIGGERS unsichtbar ──

class _CurDba(_Cur):
    def __init__(self, dba_trig=None, dba_error=None, **kw):
        super().__init__(**kw)
        self.dba_trig, self.dba_error = dba_trig, dba_error

    def execute(self, sql, params=None):
        s = " ".join(sql.split()).lower()
        if "dba_triggers" in s:
            self.calls.append((s, params))
            if self.dba_error:
                raise self.dba_error
            self._rows = [self.dba_trig] if self.dba_trig else []
            return
        return super().execute(sql, params)


def test_unsichtbar_aber_dba_sicht_liefert_zustand():
    conn = _Conn(_CurDba(user="SLIM", tables=(), synonym="V8LIVE", trig=None, dba_trig=("V8LIVE", "DISABLED")))
    st = read_state(conn)
    assert st["state"] == "inaktiv" and st["owner"] == "V8LIVE"
    assert st["grant_sql"] == "GRANT ALTER ANY TRIGGER TO SLIM;"


def test_unsichtbar_dba_sicht_kein_trigger_ist_fehlt():
    conn = _Conn(_CurDba(user="SLIM", tables=(), synonym="V8LIVE", trig=None, dba_trig=None))
    assert read_state(conn)["state"] == "fehlt"


def test_unsichtbar_ohne_dba_sicht_nennt_beide_grants():
    conn = _Conn(_CurDba(user="SLIM", tables=(), synonym="V8LIVE", trig=None,
                         dba_error=RuntimeError("ORA-00942: table or view does not exist")))
    st = read_state(conn)
    assert st["state"] == "nicht_pruefbar"
    assert st["grant_sql"] == "GRANT SELECT ON SYS.DBA_TRIGGERS TO SLIM;\nGRANT ALTER ANY TRIGGER TO SLIM;"
