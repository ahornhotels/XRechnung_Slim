"""Tests fuer slim/jobs_slim/poller.run_once.

Pure Unit-Tests gegen einen voll gemockten DB-Layer + Suite8-Mailer.
Echte DB wird NICHT angesprochen (kein RUN_DB_TESTS noetig).
"""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from slim.jobs_slim import poller
from slim.core_slim import audit_jsonl


def _mock_hotel_cfg(filename_pattern=r"Folio_IND.*_(?P<zinv_number>\d+)\.pdf$",
                    subject_pattern=""):
    return {
        "mail_strategy": "suite8",
        "suite8_recognize_filename_pattern": filename_pattern,
        "suite8_recognize_subject_pattern": subject_pattern,
        "suite8_attachment_name_template": "{zinv_number}.xml",
    }


def _wmai_row(wmai_id, filename, subject="", to=""):
    return {"wmai_id": wmai_id, "filename": filename, "subject": subject, "to": to}


@pytest.fixture
def mocked_db():
    """Erzeugt einen Context-Manager-Mock fuer get_connection().

    Der Poller ruft get_connection() jetzt EINMAL fuer find_pending_wmai
    und DANN nochmal pro WMAI — der gleiche CM-Mock muss also mehrfach
    re-enterbar sein.
    """
    conn = MagicMock(name="oracle_conn")
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=None)
    return cm, conn


def test_skipped_when_strategy_graph(tmp_path, mocked_db):
    cm, conn = mocked_db
    with patch.object(poller, "load_hotel_config",
                      return_value={"mail_strategy": "graph"}):
        s = poller.run_once(data_dir=tmp_path)
    assert s["skipped_strategy"] is True


def test_attach_ok_zinv_number_pattern(tmp_path, mocked_db):
    """Subject-Pattern mit zinv_number — der Standard-Workflow im Live-Hotel."""
    cm, conn = mocked_db
    hotel = _mock_hotel_cfg(
        filename_pattern="",
        subject_pattern=r"Rechnung Nr\.?\s*(?P<zinv_number>\d+)",
    )

    with patch.object(poller, "load_hotel_config", return_value=hotel), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(101, "irrelevant.pdf",
                                              "Ihre Rechnung Nr. 144853")]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number",
                      return_value=999), \
         patch.object(poller.invoice_fetcher, "fetch_invoice",
                      return_value={"zinv_id": 999, "header": {"id": "144853"},
                                    "lines": [], "totals": {}}), \
         patch.object(poller.invoice_validator, "validate", return_value=[]), \
         patch.object(poller.xml_builder, "build_and_validate",
                      return_value=b"<Invoice>OK</Invoice>"), \
         patch.object(poller.kosit_validator, "validate"), \
         patch.object(poller, "attach_xml_to_wmai",
                      return_value={"wmaa_id": 7, "wtxt_id": 8, "wmai_id": 101}):

        s = poller.run_once(data_dir=tmp_path)

    assert s["attached"] == 1 and s["failed"] == 0
    xmls = list((tmp_path / "xml").rglob("144853.xml"))
    assert len(xmls) == 1
    audit_files = list(tmp_path.glob("audit-*.jsonl"))
    entries = [json.loads(l) for l in audit_files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(e["event"] == "attach_ok" and e["zinv_number"] == "144853"
               for e in entries)


def test_attach_template_applies_to_archive_and_attachment(tmp_path, mocked_db):
    """Das Anhang-Namens-Template gilt fuer BEIDE Ziele: den Suite8-Anhang
    UND die Archivdatei auf der Platte (einheitlicher Name)."""
    cm, conn = mocked_db
    hotel = _mock_hotel_cfg(
        filename_pattern="",
        subject_pattern=r"Rechnung Nr\.?\s*(?P<zinv_number>\d+)",
    )
    hotel["suite8_attachment_name_template"] = "XRechnung_{zinv_number}.xml"

    with patch.object(poller, "load_hotel_config", return_value=hotel), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(101, "irrelevant.pdf",
                                              "Ihre Rechnung Nr. 144853")]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number",
                      return_value=999), \
         patch.object(poller.invoice_fetcher, "fetch_invoice",
                      return_value={"zinv_id": 999, "header": {"id": "144853"},
                                    "lines": [], "totals": {}}), \
         patch.object(poller.invoice_validator, "validate", return_value=[]), \
         patch.object(poller.xml_builder, "build_and_validate",
                      return_value=b"<Invoice>OK</Invoice>"), \
         patch.object(poller.kosit_validator, "validate"), \
         patch.object(poller, "attach_xml_to_wmai",
                      return_value={"wmaa_id": 7, "wtxt_id": 8,
                                    "wmai_id": 101}) as attach:

        s = poller.run_once(data_dir=tmp_path)

    assert s["attached"] == 1
    # Suite8-Anhang traegt den Template-Namen
    assert attach.call_args.kwargs["filename"] == "XRechnung_144853.xml"
    # Archivdatei ebenfalls (inkl. SHA256-Seitendatei)
    xmls = list((tmp_path / "xml").rglob("XRechnung_144853.xml"))
    assert len(xmls) == 1
    assert (xmls[0].parent / "XRechnung_144853.sha256").exists()


def test_attach_ok_zinv_id_pattern_uses_fetch_invoice_directly(tmp_path, mocked_db):
    """Filename-Pattern mit zinv_id — Poller MUSS direkt fetch_invoice(int(id))
    aufrufen und darf NICHT find_zinv_id_by_number nutzen (sonst greift der
    ID-Number-Bug der Big-App: ID 144853 als Number missinterpretiert)."""
    cm, conn = mocked_db
    hotel = _mock_hotel_cfg(
        filename_pattern=r"Folio_IND.*_(?P<zinv_id>\d+)\.pdf$",
        subject_pattern="",
    )

    fetched_invoice = {
        "zinv_id": 144853,
        "header": {"id": "143741"},  # echte ZINV_NUMBER fuer ID 144853
        "lines": [], "totals": {},
    }

    with patch.object(poller, "load_hotel_config", return_value=hotel), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(101, "Folio_IND_TEST_144853.pdf")]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number") as find_nr, \
         patch.object(poller.invoice_fetcher, "fetch_invoice",
                      return_value=fetched_invoice) as fetch, \
         patch.object(poller.invoice_validator, "validate", return_value=[]), \
         patch.object(poller.xml_builder, "build_and_validate", return_value=b"<X/>"), \
         patch.object(poller.kosit_validator, "validate"), \
         patch.object(poller, "attach_xml_to_wmai",
                      return_value={"wmaa_id": 7, "wtxt_id": 8, "wmai_id": 101}):

        s = poller.run_once(data_dir=tmp_path)

    assert s["attached"] == 1
    # fetch_invoice mit zinv_id=144853 (aus Filename), NICHT mit 145965 (was
    # find_zinv_id_by_number("144853") liefern wuerde)
    fetch.assert_called_once_with(144853)
    find_nr.assert_not_called()
    # Audit zeigt die ECHTE Rechnungsnummer 143741, nicht die ID 144853
    audit_files = list(tmp_path.glob("audit-*.jsonl"))
    entries = [json.loads(l) for l in audit_files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    attach_ok = [e for e in entries if e["event"] == "attach_ok"]
    assert attach_ok and attach_ok[0]["zinv_number"] == "143741"
    # XML-Archiv-Filename nutzt die echte Nummer
    assert list((tmp_path / "xml").rglob("143741.xml"))


def test_pattern_no_match_logs_and_sets_wmai_error(tmp_path, mocked_db):
    cm, conn = mocked_db
    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel_cfg()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(102, "weird.pdf", "kein match")]), \
         patch.object(poller, "get_wmai_error", return_value=None), \
         patch.object(poller, "set_wmai_error") as set_err:
        s = poller.run_once(data_dir=tmp_path)

    assert s["no_match"] == 1
    set_err.assert_called_once()
    audit_files = list(tmp_path.glob("audit-*.jsonl"))
    assert len(audit_files) == 1
    entries = [json.loads(l) for l in audit_files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert entries[0]["event"] == "pattern_no_match"
    assert entries[0]["wmai_id"] == 102


def test_validator_fail_writes_validator_fail_event(tmp_path, mocked_db):
    cm, conn = mocked_db
    issues = [
        {"field": "supplier.name", "severity": "error", "message": "Hotel-Name fehlt"},
        {"field": "customer.email", "severity": "error", "message": "Email fehlt"},
    ]
    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel_cfg()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(103, "Folio_IND_144854.pdf")]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number", return_value=8), \
         patch.object(poller.invoice_fetcher, "fetch_invoice",
                      return_value={"zinv_id": 8, "header": {}, "lines": [], "totals": {}}), \
         patch.object(poller.invoice_validator, "validate", return_value=issues), \
         patch.object(poller, "get_wmai_error", return_value=None), \
         patch.object(poller, "set_wmai_error") as set_err:
        s = poller.run_once(data_dir=tmp_path)

    assert s["failed"] == 1
    audit_files = list(tmp_path.glob("audit-*.jsonl"))
    entries = [json.loads(l) for l in audit_files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert entries[0]["event"] == "validator_fail"
    set_err.assert_called_once()
    err_arg = set_err.call_args[0][1]  # 2. Argument = error_text
    assert "Validator-Fail" in err_arg


def test_kosit_fail_classified_separately(tmp_path, mocked_db):
    from modules.kosit_validator import KositValidationError
    cm, conn = mocked_db
    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel_cfg()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(104, "Folio_IND_144855.pdf")]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number", return_value=7), \
         patch.object(poller.invoice_fetcher, "fetch_invoice",
                      return_value={"zinv_id": 7, "header": {}, "lines": [], "totals": {}}), \
         patch.object(poller.invoice_validator, "validate", return_value=[]), \
         patch.object(poller.xml_builder, "build_and_validate", return_value=b"<X/>"), \
         patch.object(poller.kosit_validator, "validate",
                      side_effect=KositValidationError(["BR-DE-5 verletzt"])), \
         patch.object(poller, "get_wmai_error", return_value=None), \
         patch.object(poller, "set_wmai_error"):
        s = poller.run_once(data_dir=tmp_path)
    assert s["failed"] == 1
    audit_files = list(tmp_path.glob("audit-*.jsonl"))
    entries = [json.loads(l) for l in audit_files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert entries[0]["event"] == "kosit_fail"


def test_spam_guard_skips_duplicate_error(tmp_path, mocked_db):
    cm, conn = mocked_db
    # WMAI hat bereits identischen Fehlertext (exakt das Format aus pattern_no_match)
    prev_err = (
        "filename='nope.pdf' subject='': "
        "Kein Pattern hat getroffen (filename='nope.pdf', subject='')"
    )
    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel_cfg()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(105, "nope.pdf")]), \
         patch.object(poller, "get_wmai_error", return_value=prev_err[:400]), \
         patch.object(poller, "set_wmai_error"):
        poller.run_once(data_dir=tmp_path)
    # Kein neuer Audit-Eintrag fuer identischen Fehler — Datei darf gar nicht entstehen
    audit_files = list(tmp_path.glob("audit-*.jsonl"))
    assert audit_files == [], f"Spam-Guard hat nicht gegriffen: {audit_files}"


def test_db_error_on_find_pending_breaks_loop(tmp_path):
    """Wenn find_pending_wmai crasht, gibt es einen poller_db_error-Audit."""
    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel_cfg()), \
         patch.object(poller, "get_connection", side_effect=RuntimeError("ORA-03113")):
        s = poller.run_once(data_dir=tmp_path)
    assert s.get("db_error") is True
    audit_files = list(tmp_path.glob("audit-*.jsonl"))
    entries = [json.loads(l) for l in audit_files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert entries[0]["event"] == "poller_db_error"


def test_per_wmai_connection_used(tmp_path, mocked_db):
    """get_connection wird pro WMAI neu aufgerufen — verhindert Cursor-Leak-Kaskade."""
    cm, conn = mocked_db
    # 3 WMAIs in find_pending
    rows = [_wmai_row(i, f"weird_{i}.pdf") for i in range(3)]
    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel_cfg()), \
         patch.object(poller, "get_connection", return_value=cm) as get_conn, \
         patch.object(poller, "find_pending_wmai", return_value=rows), \
         patch.object(poller, "get_wmai_error", return_value=None), \
         patch.object(poller, "set_wmai_error"):
        poller.run_once(data_dir=tmp_path)
    # 1× fuer find_pending + 1× pro WMAI = 4
    assert get_conn.call_count == 4


def test_zinv_not_found_classified(tmp_path, mocked_db):
    cm, conn = mocked_db
    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel_cfg()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(106, "Folio_IND_999999.pdf")]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number", return_value=None), \
         patch.object(poller, "get_wmai_error", return_value=None), \
         patch.object(poller, "set_wmai_error"):
        s = poller.run_once(data_dir=tmp_path)
    assert s["failed"] == 1
    audit_files = list(tmp_path.glob("audit-*.jsonl"))
    entries = [json.loads(l) for l in audit_files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert entries[0]["event"] == "zinv_not_found"


# ------------------------------------------------ Fehler-XML-Ablage im Poller

def test_validator_fail_ablegt_fehler_xml(tmp_path, mocked_db):
    """Bei validator_fail wird die XML trotz Fehler gerendert und unter
    xml_invalid/ abgelegt — samit der Operator die fehlenden Felder sieht."""
    cm, conn = mocked_db
    issues = [{"field": "billing_reference", "severity": "error",
               "message": "Gutschrift braucht Bezug zur Original-Rechnung"}]
    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel_cfg()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(201, "Folio_IND_48400.pdf")]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number", return_value=8), \
         patch.object(poller.invoice_fetcher, "fetch_invoice",
                      return_value={"zinv_id": 8, "header": {"id": "48400"},
                                    "lines": [], "totals": {}}), \
         patch.object(poller.invoice_validator, "validate", return_value=issues), \
         patch.object(poller.xml_builder, "render",
                      return_value=b"<CreditNote>diag</CreditNote>"), \
         patch.object(poller, "get_wmai_error", return_value=None), \
         patch.object(poller, "set_wmai_error"):
        s = poller.run_once(data_dir=tmp_path)

    assert s["failed"] == 1
    invalid = list((tmp_path / "xml_invalid").rglob("*48400*.xml"))
    assert len(invalid) == 1
    assert invalid[0].read_bytes() == b"<CreditNote>diag</CreditNote>"
    # error.txt-Beiblatt mit Fehlerklasse liegt daneben
    assert (invalid[0].parent / "48400.error.txt").exists()


def test_kosit_fail_ablegt_fehler_xml(tmp_path, mocked_db):
    from modules.kosit_validator import KositValidationError
    cm, conn = mocked_db
    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel_cfg()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(202, "Folio_IND_48401.pdf")]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number", return_value=7), \
         patch.object(poller.invoice_fetcher, "fetch_invoice",
                      return_value={"zinv_id": 7, "header": {"id": "48401"},
                                    "lines": [], "totals": {}}), \
         patch.object(poller.invoice_validator, "validate", return_value=[]), \
         patch.object(poller.xml_builder, "build_and_validate", return_value=b"<X/>"), \
         patch.object(poller.xml_builder, "render", return_value=b"<X/>"), \
         patch.object(poller.kosit_validator, "validate",
                      side_effect=KositValidationError(["BR-DE-5 verletzt"])), \
         patch.object(poller, "get_wmai_error", return_value=None), \
         patch.object(poller, "set_wmai_error"):
        s = poller.run_once(data_dir=tmp_path)

    assert s["failed"] == 1
    assert list((tmp_path / "xml_invalid").rglob("*48401*.xml"))


def test_zinv_not_found_legt_keine_fehler_xml_ab(tmp_path, mocked_db):
    """Nicht-baubare Fehler (kein inv) duerfen keine Fehler-XML erzeugen."""
    cm, conn = mocked_db
    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel_cfg()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(203, "Folio_IND_999999.pdf")]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number", return_value=None), \
         patch.object(poller, "get_wmai_error", return_value=None), \
         patch.object(poller, "set_wmai_error"):
        poller.run_once(data_dir=tmp_path)
    assert not (tmp_path / "xml_invalid").exists()


def test_erfolg_raeumt_vorherige_fehler_xml_auf(tmp_path, mocked_db):
    """Ein geglueckter Retval loescht eine zuvor abgelegte Fehler-XML."""
    from slim.core_slim import archive_fs
    # Vorlauf: es liegt bereits eine Fehler-XML fuer 144853 vor
    archive_fs.save_invalid_xml(tmp_path, "144853", b"<alt/>",
                                event="validator_fail", error_text="frueher")
    assert list((tmp_path / "xml_invalid").rglob("*144853*.xml"))

    cm, conn = mocked_db
    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel_cfg()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(204, "Folio_IND_144853.pdf")]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number", return_value=999), \
         patch.object(poller.invoice_fetcher, "fetch_invoice",
                      return_value={"zinv_id": 999, "header": {"id": "144853"},
                                    "lines": [], "totals": {}}), \
         patch.object(poller.invoice_validator, "validate", return_value=[]), \
         patch.object(poller.xml_builder, "build_and_validate",
                      return_value=b"<Invoice>OK</Invoice>"), \
         patch.object(poller.kosit_validator, "validate"), \
         patch.object(poller, "attach_xml_to_wmai",
                      return_value={"wmaa_id": 7, "wtxt_id": 8, "wmai_id": 204}):
        s = poller.run_once(data_dir=tmp_path)

    assert s["attached"] == 1
    # Fehler-XML wurde aufgeraeumt
    assert list((tmp_path / "xml_invalid").rglob("*144853*.xml")) == []


def test_render_fehler_bei_ablage_crasht_poller_nicht(tmp_path, mocked_db):
    """Schlaegt sogar das Diagnose-Rendern fehl, laeuft der normale
    Fehlerpfad (failed++, Audit) unveraendert weiter."""
    cm, conn = mocked_db
    issues = [{"field": "x", "severity": "error", "message": "irgendwas"}]
    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel_cfg()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[_wmai_row(205, "Folio_IND_48402.pdf")]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number", return_value=8), \
         patch.object(poller.invoice_fetcher, "fetch_invoice",
                      return_value={"zinv_id": 8, "header": {"id": "48402"},
                                    "lines": [], "totals": {}}), \
         patch.object(poller.invoice_validator, "validate", return_value=issues), \
         patch.object(poller.xml_builder, "render",
                      side_effect=RuntimeError("Jinja kaputt")), \
         patch.object(poller, "get_wmai_error", return_value=None), \
         patch.object(poller, "set_wmai_error") as set_err:
        s = poller.run_once(data_dir=tmp_path)

    assert s["failed"] == 1
    set_err.assert_called_once()
    audit_files = list(tmp_path.glob("audit-*.jsonl"))
    entries = [json.loads(l) for l in audit_files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert entries[0]["event"] == "validator_fail"
