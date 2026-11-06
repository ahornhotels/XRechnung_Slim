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


def test_fehler_beim_leeren_pdf_bleibt_xml_geht():
    """Z. B. ORA-00904 (RTF-Spalte fehlt in einer Suite8-Version): Das PDF
    bleibt, die XML wird trotzdem angehaengt und die Mail entblockt - lieber
    PDF mitsenden als die Mail dauerhaft blockieren."""
    conn = _Conn(fail_on="UPDATE WMAI SET WMAI_ATTACHMENT_WTXT_ID")
    res = _attach(conn, remove_pdf=True)
    assert res["pdf_removed"] is False and "DB kaputt" in res["pdf_error"]
    assert conn.commits == 1 and conn.rollbacks == 0
    assert any(s.startswith("UPDATE WMAI SET WMAI_BLOCKSEND=0") for s in conn.log)


# --- Poller reicht xml_only durch und protokolliert ---

@pytest.mark.parametrize("reason,removed", [("membership", True), ("global", False), (None, False)])
def test_poller_reicht_xml_only_durch(tmp_path, reason, removed):
    import json
    from unittest.mock import MagicMock, patch
    from slim.jobs_slim import poller
    from tests_slim.test_poller_loop import _mock_hotel_cfg, _wmai_row

    conn = MagicMock(); cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn); cm.__exit__ = MagicMock(return_value=None)
    attach = MagicMock(return_value={"wmaa_id": 7, "wtxt_id": 8, "wmai_id": 101, "pdf_removed": removed})
    hotel = _mock_hotel_cfg(filename_pattern="", subject_pattern=r"Rechnung Nr\.?\s*(?P<zinv_number>\d+)")
    with patch.object(poller, "load_hotel_config", return_value=hotel), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai", return_value=[_wmai_row(101, "x.pdf", "Rechnung Nr. 144853")]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number", return_value=999), \
         patch.object(poller.invoice_fetcher, "fetch_invoice",
                      return_value={"zinv_id": 999, "header": {"id": "144853"}, "lines": [],
                                    "totals": {}, "xml_only": reason}), \
         patch.object(poller.invoice_validator, "validate", return_value=[]), \
         patch.object(poller.xml_builder, "build_and_validate", return_value=b"<Invoice/>"), \
         patch.object(poller.kosit_validator, "validate"), \
         patch.object(poller, "attach_xml_to_wmai", attach):
        poller.run_once(data_dir=tmp_path)

    assert attach.call_args.kwargs["remove_pdf"] is bool(reason)
    entries = [json.loads(l) for f in tmp_path.glob("audit-*.jsonl")
               for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = next(e for e in entries if e["event"] == "attach_ok")
    if reason:
        assert ok["details"]["xml_only"] == reason
        assert ok["details"]["pdf_removed"] is removed
        assert ok["details"].get("pdf_not_removed", False) is (not removed)
    else:
        assert "xml_only" not in ok["details"]
