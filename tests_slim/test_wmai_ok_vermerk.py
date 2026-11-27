"""Nach erfolgreichem Anhaengen steht in WMAI_ERROR der Vermerk 'XRechnung OK'
(in Suite8 sichtbar) - in derselben Transaktion wie Anhang und Freigabe."""
from unittest.mock import MagicMock

from modules import suite8_mailer


def _conn(rowcount=1):
    cur = MagicMock()
    cur.fetchone.side_effect = [(501,), (601,)]
    cur.rowcount = rowcount
    return MagicMock(cursor=MagicMock(return_value=cur)), cur


def test_anhaengen_schreibt_xrechnung_ok():
    conn, cur = _conn()
    suite8_mailer.attach_xml_to_wmai(wmai_id=7, xml_bytes=b"<x/>", filename="1.xml", conn=conn)
    sql, binds = cur.execute.call_args_list[-1][0]
    assert " ".join(sql.split()) == "UPDATE WMAI SET WMAI_ERROR = :vermerk WHERE WMAI_ID = :wmai_id"
    assert binds == {"vermerk": "XRechnung OK", "wmai_id": 7} and suite8_mailer.OK_VERMERK == "XRechnung OK"
    conn.commit.assert_called_once()


def test_ohne_freigabe_kein_vermerk():
    conn, cur = _conn(rowcount=0)
    try:
        suite8_mailer.attach_xml_to_wmai(wmai_id=7, xml_bytes=b"<x/>", filename="1.xml", conn=conn)
        assert False, "haette abbrechen muessen"
    except RuntimeError:
        pass
    assert not [c for c in cur.execute.call_args_list if "WMAI_ERROR" in c[0][0]]
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
