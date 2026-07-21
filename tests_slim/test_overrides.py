"""Tests fuer slim/core_slim/overrides.py + Poller-Hook."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from slim.core_slim import overrides
from slim.jobs_slim import poller


def test_load_returns_empty_when_no_file(tmp_path):
    assert overrides.load(tmp_path, 42) == {}


def test_save_then_load(tmp_path):
    overrides.save(tmp_path, 42, {"customername": "Max"})
    assert overrides.load(tmp_path, 42) == {"customername": "Max"}


def test_save_filters_unknown_keys(tmp_path):
    saved = overrides.save(tmp_path, 1, {
        "customername": "Max",
        "evil_key": "bypass",
        "id": "manipulated",  # nicht in ALLOWED_KEYS
    })
    assert saved == {"customername": "Max"}
    assert overrides.load(tmp_path, 1) == {"customername": "Max"}


def test_billingref_id_override_leert_verwaistes_issuedate(tmp_path):
    """Korrigiert der Operator per Override nur die billingreferenceid (weil
    der Auto-Fallback die falsche Rechnung traf), darf das vom Fallback
    gesetzte issuedate der FALSCHEN Rechnung nicht dranbleiben."""
    overrides.save(tmp_path, 42, {"billingreferenceid": "12345"})
    inv = {"header": {"billingreferenceid": "98765",
                      "billingreferenceissuedate": "2026-06-30"}}
    out = overrides.apply_to_invoice(tmp_path, 42, inv)
    assert out["header"]["billingreferenceid"] == "12345"
    assert not out["header"].get("billingreferenceissuedate")


def test_billingref_id_und_date_override_bleibt(tmp_path):
    """Setzt der Override id UND date, bleibt das date erhalten."""
    overrides.save(tmp_path, 42, {"billingreferenceid": "12345",
                                  "billingreferenceissuedate": "2026-05-01"})
    inv = {"header": {"billingreferenceid": "98765",
                      "billingreferenceissuedate": "2026-06-30"}}
    out = overrides.apply_to_invoice(tmp_path, 42, inv)
    assert out["header"]["billingreferenceissuedate"] == "2026-05-01"


def test_save_drops_empty_values(tmp_path):
    saved = overrides.save(tmp_path, 1, {
        "customername": "Max",
        "customerstreetname": "",
        "customercityname": "   ",  # whitespace only
        "customerendpointid": None,
    })
    assert saved == {"customername": "Max"}


def test_save_empty_removes_file(tmp_path):
    overrides.save(tmp_path, 1, {"customername": "Max"})
    assert (tmp_path / "overrides" / "1.json").exists()
    overrides.save(tmp_path, 1, {})
    assert not (tmp_path / "overrides" / "1.json").exists()


def test_delete(tmp_path):
    overrides.save(tmp_path, 7, {"customername": "X"})
    assert overrides.delete(tmp_path, 7) is True
    assert overrides.delete(tmp_path, 7) is False  # idempotent


def test_apply_to_invoice_merges_header(tmp_path):
    overrides.save(tmp_path, 1, {"customerendpointid": "x@y.z"})
    inv = {"header": {"id": "123", "customername": "Original"},
           "lines": [], "totals": {}}
    out = overrides.apply_to_invoice(tmp_path, 1, inv)
    assert out["header"]["customerendpointid"] == "x@y.z"
    assert out["header"]["customername"] == "Original"  # unangetastet
    # Original-Dict NICHT mutiert (immutability-Garantie)
    assert "customerendpointid" not in inv["header"]


def test_apply_to_invoice_no_overrides_returns_same(tmp_path):
    inv = {"header": {"id": "123"}, "lines": []}
    out = overrides.apply_to_invoice(tmp_path, 999, inv)
    assert out is inv  # gleiches Objekt, kein Kopier-Aufwand


def test_apply_to_invoice_ignores_disallowed_in_file(tmp_path):
    """Wenn jemand manuell eine Override-Datei mit unerlaubten Keys schreibt,
    sollen die ignoriert werden (defense in depth)."""
    path = tmp_path / "overrides" / "5.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "customername": "OK",
        "id": "SHOULDNT_OVERRIDE",  # nicht in ALLOWED_KEYS
    }), encoding="utf-8")
    inv = {"header": {"id": "ORIGINAL"}, "lines": []}
    out = overrides.apply_to_invoice(tmp_path, 5, inv)
    assert out["header"]["customername"] == "OK"
    assert out["header"]["id"] == "ORIGINAL"


def test_load_malformed_json_returns_empty(tmp_path):
    path = tmp_path / "overrides" / "9.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    assert overrides.load(tmp_path, 9) == {}


def test_list_all(tmp_path):
    overrides.save(tmp_path, 1, {"customername": "A"})
    overrides.save(tmp_path, 2, {"customername": "B"})
    all_ov = overrides.list_all(tmp_path)
    assert set(all_ov.keys()) == {1, 2}


# ─────────────── Poller-Hook: Override-Apply + Cleanup ───────────────

def _mock_hotel():
    return {
        "mail_strategy": "suite8",
        "suite8_recognize_subject_pattern": r"R (?P<zinv_number>\d+)",
        "suite8_recognize_filename_pattern": "",
        "suite8_attachment_name_template": "{zinv_number}.xml",
    }


@pytest.fixture
def mocked_db():
    conn = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=None)
    return cm, conn


def test_poller_applies_override_before_validator(tmp_path, mocked_db):
    """Override im Filesystem muss in inv['header'] gemerget sein,
    BEVOR der Validator drueberlaeuft. So kann ein vorher fehlendes
    Pflichtfeld nachgereicht werden."""
    cm, conn = mocked_db
    overrides.save(tmp_path, 101, {"customerendpointid": "kunde@example.com"})

    fetched = {"zinv_id": 999, "header": {"id": "12345"},
               "lines": [], "totals": {}}

    captured_inv = []
    def fake_validate(inv):
        captured_inv.append(inv)
        return []

    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[{"wmai_id": 101, "filename": "",
                                     "subject": "R 12345", "to": ""}]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number",
                      return_value=999), \
         patch.object(poller.invoice_fetcher, "fetch_invoice", return_value=fetched), \
         patch.object(poller.invoice_validator, "validate", side_effect=fake_validate), \
         patch.object(poller.xml_builder, "build_and_validate", return_value=b"<X/>"), \
         patch.object(poller.kosit_validator, "validate"), \
         patch.object(poller, "attach_xml_to_wmai",
                      return_value={"wmaa_id": 1, "wtxt_id": 2, "wmai_id": 101}):
        poller.run_once(data_dir=tmp_path)

    # Validator hat eine Version mit ueberschriebenem Feld bekommen
    assert captured_inv[0]["header"]["customerendpointid"] == "kunde@example.com"


def test_poller_deletes_override_after_successful_attach(tmp_path, mocked_db):
    cm, conn = mocked_db
    overrides.save(tmp_path, 202, {"customername": "Override"})
    assert (tmp_path / "overrides" / "202.json").exists()

    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[{"wmai_id": 202, "filename": "",
                                     "subject": "R 67890", "to": ""}]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number",
                      return_value=8), \
         patch.object(poller.invoice_fetcher, "fetch_invoice",
                      return_value={"zinv_id": 8, "header": {"id": "67890"},
                                    "lines": [], "totals": {}}), \
         patch.object(poller.invoice_validator, "validate", return_value=[]), \
         patch.object(poller.xml_builder, "build_and_validate", return_value=b"<X/>"), \
         patch.object(poller.kosit_validator, "validate"), \
         patch.object(poller, "attach_xml_to_wmai",
                      return_value={"wmaa_id": 1, "wtxt_id": 2, "wmai_id": 202}):
        poller.run_once(data_dir=tmp_path)

    assert not (tmp_path / "overrides" / "202.json").exists()


def test_poller_keeps_override_after_failed_attach(tmp_path, mocked_db):
    """Wenn der Lauf fehlschlaegt, MUSS das Override liegenbleiben — sonst
    muesste der Operator es bei jedem Retry neu eingeben."""
    cm, conn = mocked_db
    overrides.save(tmp_path, 303, {"customername": "Override"})

    with patch.object(poller, "load_hotel_config", return_value=_mock_hotel()), \
         patch.object(poller, "get_connection", return_value=cm), \
         patch.object(poller, "find_pending_wmai",
                      return_value=[{"wmai_id": 303, "filename": "",
                                     "subject": "R 11111", "to": ""}]), \
         patch.object(poller.invoice_fetcher, "find_zinv_id_by_number",
                      return_value=8), \
         patch.object(poller.invoice_fetcher, "fetch_invoice",
                      return_value={"zinv_id": 8, "header": {"id": "11111"},
                                    "lines": [], "totals": {}}), \
         patch.object(poller.invoice_validator, "validate",
                      return_value=[{"field": "x", "severity": "error",
                                     "message": "fehlt"}]), \
         patch.object(poller, "get_wmai_error", return_value=None), \
         patch.object(poller, "set_wmai_error"):
        poller.run_once(data_dir=tmp_path)

    # Override muss noch da sein
    assert (tmp_path / "overrides" / "303.json").exists()
