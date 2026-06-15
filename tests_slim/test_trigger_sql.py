"""Tests für slim/api_slim/trigger_sql.py — Python→Oracle-Regex-Konvertierung.

Hintergrund: Oracle REGEXP_LIKE versteht weder Python-Named-Groups
``(?P<name>...)`` noch Non-Capturing-Groups ``(?:...)``. Beide müssen
vor dem Einbau ins Trigger-SQL in normale Capture-Groups umgewandelt
werden, sonst matcht der Trigger NIE (stilles Komplettversagen).
"""
import json

import pytest

from slim.api_slim.trigger_sql import (
    _python_to_oracle_regex,
    build_block_trigger_sql,
)


def test_named_group_converted():
    assert _python_to_oracle_regex(r"Rechnung\s*(?P<zinv_number>\d+)") == \
        r"Rechnung\s*(\d+)"


def test_named_group_zinv_id_converted():
    assert _python_to_oracle_regex(r"Folio_(?P<zinv_id>\d+)\.pdf") == \
        r"Folio_(\d+)\.pdf"


def test_non_capturing_group_converted():
    # Alternation für mehrsprachige Subjects ("Ihre Rechnung" / "Invoice
    # number") braucht (?:...) — Oracle kennt das nicht, muss zu (...) werden.
    assert _python_to_oracle_regex(r"(?:Ihre\s+Rechnung|Invoice\s+number)") == \
        r"(Ihre\s+Rechnung|Invoice\s+number)"


def test_combined_alternation_and_named_group():
    pat = r"(?:Ihre\s+Rechnung|Invoice\s+number)\D{0,10}(?P<zinv_number>\d{3,})"
    assert _python_to_oracle_regex(pat) == \
        r"(Ihre\s+Rechnung|Invoice\s+number)\D{0,10}(\d{3,})"


def test_plain_pattern_unchanged():
    assert _python_to_oracle_regex(r"Folio.*\.pdf$") == r"Folio.*\.pdf$"


# ─────────────────────── Idempotenz-Guard ───────────────────────
# Der Trigger darf eine Mail NICHT erneut blocken, wenn bereits ein
# XRechnung-XML an ihr haengt. Schuetzt gegen Re-Block-Endlosschleife,
# falls der Suite8-Mailspooler beim Versand zuerst WMAI_NO_OF_ATTEMPTS
# erhoeht, waehrend WMAI_SENT noch 0 ist.


def test_guard_present_for_subject_pattern():
    sql = build_block_trigger_sql(
        fn_pat="", sub_pat=r"Rechnung\s*(?P<zinv_number>\d+)")
    assert "v_has_xml" in sql
    assert "SELECT COUNT(*)" in sql
    assert "WMAA_WMAI_ID = :NEW.WMAI_ID" in sql
    assert "LOWER(WMAA_FILENAME) LIKE '%.xml'" in sql


def test_guard_only_blocks_when_no_xml_attached():
    sql = build_block_trigger_sql(
        fn_pat="", sub_pat=r"Rechnung\s*(?P<zinv_number>\d+)")
    # BLOCKSEND wird nur innerhalb des v_has_xml=0-Zweigs gesetzt.
    assert "IF v_has_xml = 0 THEN" in sql
    guard_pos = sql.index("IF v_has_xml = 0 THEN")
    block_pos = sql.index(":NEW.WMAI_BLOCKSEND := 1")
    assert guard_pos < block_pos


def test_guard_declares_variable():
    sql = build_block_trigger_sql(fn_pat="Folio.*\\.pdf$", sub_pat="")
    assert "DECLARE" in sql
    assert "v_has_xml NUMBER := 0" in sql


def test_trigger_still_oracle_converts_pattern():
    sql = build_block_trigger_sql(
        fn_pat="",
        sub_pat=r"(?:Ihre\s+Rechnung|Invoice\s+number)\D{0,10}(?P<zinv_number>\d{3,})")
    # Named-Group und Non-Capturing-Group muessen in der REGEXP_LIKE-Klausel
    # Oracle-konvertiert sein. (Der Header-Kommentar zeigt bewusst das
    # Original-Python-Pattern als DBA-Referenz, daher nur die SQL-Zeile pruefen.)
    regexp_line = next(l for l in sql.splitlines() if "REGEXP_LIKE" in l)
    assert "(?P<" not in regexp_line
    assert "(?:" not in regexp_line
    assert "(Ihre\\s+Rechnung|Invoice\\s+number)" in regexp_line
