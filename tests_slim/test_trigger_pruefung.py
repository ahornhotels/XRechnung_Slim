"""Tests: Slim liest den Trigger WMAI_XRECHNUNG_BLOCK aus Suite8 und meldet,
was nicht zum Standard passt (Warnung oben auf der Seite Konfiguration > XRechnung)."""
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from slim.api_slim import trigger_sql as ts
from slim.core_slim import trigger_state

SUB = r"Rechnung\s+Nr\.?\s*(?P<zinv_number>\d+)"


def _standard(fn="", sub=SUB):
    """Rumpf, wie ihn Oracle in ALL_TRIGGERS.TRIGGER_BODY ablegt (ab DECLARE)."""
    sql = ts.build_block_trigger_sql(fn, sub)
    return sql[sql.index("DECLARE"):].rstrip().rstrip("/").rstrip()


HAUS = """DECLARE
  v_has_xml NUMBER := 0;
  v_is_company NUMBER := 0;
  v_tax NUMBER := 0;
BEGIN
    IF lower(:NEW.WMAI_SUBJECT) like '%rechnung%'
     AND REGEXP_LIKE(:NEW.WMAI_SUBJECT, '\\#\\s*(\\d+)', 'i') THEN
      -- schon eine XML an der Mail?
      SELECT COUNT(*) INTO v_has_xml
        FROM WMAA
       WHERE WMAA_WMAI_ID = :NEW.WMAI_ID AND LOWER(WMAA_FILENAME) LIKE '%.xml';
      select xcms_type into v_is_company
       from zinv, xcms
       where zinv_xcms_id=xcms_id
       and zinv_number=REGEXP_SUBSTR(:NEW.WMAI_SUBJECT, '\\#\\s*(\\d+)', 1, 1, 'i', 1);
      /* select sum(x) into v_tax from auskommentiert where 1=1; */
      select sum(zpos.ZPOS_QUANTITY*zpos_unitprice) into v_tax
       from zpil, zpos, zinv
       where zpos_id=zpil_zpos_id and zpos_cdt=2 and zpil_zinv_id=zinv_id;
      IF v_has_xml = 0 and v_is_company=1 and v_tax<>0 THEN
        :NEW.WMAI_BLOCKSEND := 1;
      END IF;
  END IF;
END;"""


# ───────────────────────── Vergleich ─────────────────────────

def test_standard_trigger_ohne_abweichung():
    assert ts.trigger_abweichungen("INSERT OR UPDATE", _standard(), "", SUB) == []
    assert ts.trigger_abweichungen("INSERT OR UPDATE", _standard(r"Folio_(?P<zinv_id>\d+)\.pdf$", ""),
                                   r"Folio_(?P<zinv_id>\d+)\.pdf$", "") == []


def test_schreibweise_und_kommentare_sind_keine_abweichung():
    body = _standard()
    anders = re.sub(r"--[^\n]*", "", body)                 # Kommentare weg
    anders = re.sub(r"[ \t]+", "  ", anders).replace("SELECT COUNT(*)", "select count(*)")
    assert anders != body
    assert ts.trigger_abweichungen("insert or update", anders, "", SUB) == []


def test_text_in_anfuehrungszeichen_wird_genau_verglichen():
    """Ein anderes Muster ist eine echte Abweichung, auch wenn sonst alles gleich ist."""
    ab = ts.trigger_abweichungen("INSERT OR UPDATE", _standard(), "", r"Invoice\s+(?P<zinv_number>\d+)")
    assert len(ab) == 1 and "Muster" in ab[0]


def test_haus_trigger_nennt_jede_abweichung():
    ab = ts.trigger_abweichungen("INSERT", HAUS, "", SUB)
    text = "\n".join(ab)
    assert "INSERT OR UPDATE" in text                                   # Ausloeser
    # zusaetzliche Tabellen; Kommentar und Standardtabelle WMAA zaehlen nicht
    assert "liest zusätzlich aus ZINV, XCMS, ZPIL, ZPOS." in text
    assert "AUSKOMMENTIERT" not in text
    assert "3 Abfragen" in text and "Fehlerbehandlung" in text
    assert "Muster" in text


def test_abfragen_mit_fehlerbehandlung_werden_nicht_als_abbruchgefahr_gemeldet():
    mit = HAUS.replace("END;", "EXCEPTION WHEN OTHERS THEN NULL;\nEND;")
    assert "Fehlerbehandlung" not in "\n".join(ts.trigger_abweichungen("INSERT", mit, "", SUB))


def test_unbekannte_abweichung_wird_allgemein_gemeldet():
    body = _standard().replace(":NEW.WMAI_BLOCKSEND := 1;", ":NEW.WMAI_BLOCKSEND := 1; :NEW.WMAI_ERROR := NULL;")
    ab = ts.trigger_abweichungen("INSERT OR UPDATE", body, "", SUB)
    assert len(ab) == 1 and "Standard" in ab[0]


# ───────────────────────── Lesen ─────────────────────────

def test_read_source_liest_ausloeser_und_rumpf():
    cur = MagicMock()
    cur.fetchone.return_value = ("INSERT OR UPDATE", "DECLARE x NUMBER; BEGIN NULL; END;")
    conn = MagicMock(cursor=MagicMock(return_value=cur))
    with patch.object(trigger_state, "read_state",
                      return_value={"state": "aktiv", "owner": "V8", "user": "V8", "error": None, "grant_sql": None}):
        q = trigger_state.read_source(conn)
    assert q["state"] == "aktiv" and q["event"] == "INSERT OR UPDATE" and q["body"].startswith("DECLARE")
    sql, binds = cur.execute.call_args[0]
    assert sql.lstrip().lower().startswith("select") and binds == {"n": "WMAI_XRECHNUNG_BLOCK", "o": "V8"}


def test_read_source_ohne_trigger_oder_bei_fehler():
    conn = MagicMock()
    with patch.object(trigger_state, "read_state",
                      return_value={"state": "fehlt", "owner": None, "user": "V8", "error": None, "grant_sql": None}):
        q = trigger_state.read_source(conn)
    assert q["state"] == "fehlt" and q["body"] is None
    conn.cursor.assert_not_called()
    cur = MagicMock()
    cur.execute.side_effect = RuntimeError("ORA-00942")
    conn = MagicMock(cursor=MagicMock(return_value=cur))
    with patch.object(trigger_state, "read_state",
                      return_value={"state": "aktiv", "owner": "DBA1", "user": "V8", "error": None, "grant_sql": None}):
        q = trigger_state.read_source(conn)
    assert q["state"] == "aktiv" and q["body"] is None and "ORA-00942" in q["error"]


# ───────────────────────── API ─────────────────────────

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(ts.router)
    return TestClient(app)


def _api(client, quelle):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock())
    cm.__exit__ = MagicMock(return_value=None)
    with patch.object(ts, "get_connection", return_value=cm), \
         patch.object(ts.trigger_state, "read_source", return_value=quelle), \
         patch.object(ts, "load_json", return_value={"suite8_recognize_subject_pattern": SUB}):
        return client.get("/api/trigger-pruefung").json()


def test_api_meldet_angepassten_trigger(client):
    r = _api(client, {"state": "aktiv", "event": "INSERT", "body": HAUS, "error": None})
    assert r["angepasst"] is True and len(r["abweichungen"]) >= 3 and r["quelltext"] == HAUS


def test_api_standard_und_nicht_lesbar(client):
    r = _api(client, {"state": "aktiv", "event": "INSERT OR UPDATE", "body": _standard(), "error": None})
    assert r["angepasst"] is False and r["abweichungen"] == []
    r = _api(client, {"state": "nicht_pruefbar", "event": None, "body": None, "error": "keine Sicht"})
    assert r["angepasst"] is None and r["abweichungen"] == [] and r["error"] == "keine Sicht"


def test_api_ohne_datenbank(client):
    with patch.object(ts, "get_connection", side_effect=RuntimeError("keine DB")):
        r = client.get("/api/trigger-pruefung").json()
    assert r["angepasst"] is None and "keine DB" in r["error"]


def test_einstellungsseite_warnt_oben():
    html = (Path(__file__).resolve().parent.parent / "slim" / "frontend" / "settings.html").read_text(encoding="utf-8")
    assert "/api/trigger-pruefung" in html and "angepasster Trigger" in html
    assert html.index('id="trigger-warnung"') < html.index('id="sections"')
