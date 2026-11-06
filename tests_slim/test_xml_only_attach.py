"""Tests: Nur-XML-Versand - PDF-Hauptanhang der Suite8-Mail entfernen.

Das Rechnungs-PDF ist in Suite8 der Hauptanhang der Mail selbst
(WMAI_ATTACHMENT_WTXT_ID / WMAI_ATTACHMENT_FILE_NAME), kein WMAA-Eintrag.
Slim leert nur diesen Verweis, in derselben Transaktion wie das Anhaengen der
XML, und loescht nie etwas (WTXT bleibt, weil Korrespondenz Blobs teilt).
"""
import pytest

from modules import suite8_mailer


class _Cur:
    def __init__(self, log, pdf_rows=1, fail_on=None):
        self.log, self.pdf_rows, self.fail_on = log, pdf_rows, fail_on
        self.rowcount = 0
        self._next = 0

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.log.append(s)
        if self.fail_on and self.fail_on in s:
            raise RuntimeError("DB kaputt")
        if "NEXTVAL" in s:
            self._next += 1
            return
        if s.startswith("UPDATE WMAI SET WMAI_ATTACHMENT_WTXT_ID"):
            self.rowcount = self.pdf_rows
        elif s.startswith("UPDATE WMAI SET WMAI_BLOCKSEND=0"):
            self.rowcount = 1
        else:
            self.rowcount = 1

    def fetchone(self):
        return (100 + self._next,)


class _Conn:
    def __init__(self, **kw):
        self.log, self.commits, self.rollbacks = [], 0, 0
        self.kw = kw

    def cursor(self):
        return _Cur(self.log, **self.kw)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _attach(conn, **kw):
    return suite8_mailer.attach_xml_to_wmai(wmai_id=7, xml_bytes=b"<x/>", filename="1.xml", conn=conn, **kw)


def test_ohne_remove_pdf_kein_update():
    conn = _Conn()
    res = _attach(conn)
    assert not any("WMAI_ATTACHMENT_WTXT_ID" in s and s.startswith("UPDATE") for s in conn.log)
    assert res["pdf_removed"] is False


def test_remove_pdf_leert_verweis_vor_entblocken():
    conn = _Conn()
    res = _attach(conn, remove_pdf=True)
    upd = [i for i, s in enumerate(conn.log) if s.startswith("UPDATE WMAI SET WMAI_ATTACHMENT_WTXT_ID")]
    unblock = [i for i, s in enumerate(conn.log) if s.startswith("UPDATE WMAI SET WMAI_BLOCKSEND=0")]
    assert len(upd) == 1 and upd[0] < unblock[0]
    sql = conn.log[upd[0]]
    for cond in ("WMAI_ATTACHMENT_FILE_NAME = NULL", "WMAI_BLOCKSEND=1", "WMAI_SENT=0",
                 "LIKE '%.pdf'", "WMAI_ATTACHMENT_RTF_WTXT_ID IS NULL"):
        assert cond in sql, cond
    assert not any(s.startswith("DELETE") or s.startswith("UPDATE WTXT") for s in conn.log)
    assert res["pdf_removed"] is True and conn.commits == 1


def test_remove_pdf_null_zeilen_kein_fehler():
    conn = _Conn(pdf_rows=0)
    res = _attach(conn, remove_pdf=True)
    assert res["pdf_removed"] is False and conn.commits == 1


def test_fehler_beim_leeren_rollback():
    conn = _Conn(fail_on="UPDATE WMAI SET WMAI_ATTACHMENT_WTXT_ID")
    with pytest.raises(RuntimeError):
        _attach(conn, remove_pdf=True)
    assert conn.rollbacks == 1 and conn.commits == 0
