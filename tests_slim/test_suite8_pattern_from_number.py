"""Tests für die datums-robuste, kombinierte Pattern-Erzeugung (Slim).

Hintergrund: Die alte Heuristik `generate_pattern_from_example` rät die
Rechnungsnummer als „längste Zahl" — bei Datümern im Betreff greift das
daneben. Der neue Weg: der Operator tippt die echte Rechnungsnummer ein,
und die App ankert auf den Text davor. Für mehrsprachige Hotels werden
ZWEI Beispiele (deutsch + englisch) zu EINEM kombinierten Regex
verschmolzen.

Die Big-App-Funktion `generate_pattern_from_example` bleibt unangetastet
(separate Tests in tests/).
"""
import re

import pytest

from modules.suite8_pattern import generate_combined_pattern_from_numbers


def _matches(pattern: str, text: str, group: str = "zinv_number") -> str | None:
    m = re.search(pattern, text, flags=re.IGNORECASE)
    return m.group(group) if m else None


# ───────────────────── Kombiniert (deutsch + englisch) ─────────────────────

def test_combines_two_languages_into_one_pattern():
    res = generate_combined_pattern_from_numbers([
        {"text": "Wir sagen Danke - Ihre Rechnung Nr. 144853", "number": "144853"},
        {"text": "Your invoice - Invoice number 144853", "number": "144853"},
    ])
    assert res["ok"] is True
    # Alternation für beide Sprachen, EINE Named-Group.
    assert "(?:" in res["pattern"]
    assert res["pattern"].count("(?P<zinv_number>") == 1
    # Trifft beide echten Betreffe.
    assert _matches(res["pattern"], "Ihre Rechnung Nr. 144853") == "144853"
    assert _matches(res["pattern"], "Invoice number 144853") == "144853"


def test_combined_pattern_matches_each_examples_own_number():
    res = generate_combined_pattern_from_numbers([
        {"text": "Ihre Rechnung Nr. 1001", "number": "1001"},
        {"text": "Invoice number 2002", "number": "2002"},
    ])
    assert res["ok"] is True
    assert _matches(res["pattern"], "Ihre Rechnung Nr. 1001") == "1001"
    assert _matches(res["pattern"], "Invoice number 2002") == "2002"
    assert res["matched"] == ["1001", "2002"]


# ───────────────────────── Datums-Robustheit ─────────────────────────

def test_typed_number_beats_longer_date_in_subject():
    # Datum (8-stellig) ist länger als die Rechnungsnummer (4-stellig).
    res = generate_combined_pattern_from_numbers([
        {"text": "Rechnung 1448 fällig am 20260615", "number": "1448"},
    ])
    assert res["ok"] is True
    assert _matches(res["pattern"], "Rechnung 1448 fällig am 20260615") == "1448"


def test_number_inside_longer_number_rejected():
    # Getippt 1448, aber im Betreff steht 144853 — keine eigenständige Zahl.
    res = generate_combined_pattern_from_numbers([
        {"text": "Ihre Rechnung 144853", "number": "1448"},
    ])
    assert res["ok"] is False
    assert "eigenständige" in res["error"].lower() or "eigenstaendige" in res["error"].lower()


# ───────────────────────── Einzel-Beispiel ─────────────────────────

def test_single_example_no_alternation():
    res = generate_combined_pattern_from_numbers([
        {"text": "Ihre Rechnung Nr. 144853", "number": "144853"},
    ])
    assert res["ok"] is True
    assert "(?:" not in res["pattern"]
    assert _matches(res["pattern"], "Ihre Rechnung Nr. 144853") == "144853"


def test_identical_anchors_deduplicated():
    # Beide Beispiele liefern denselben Anker → keine sinnlose (?:a|a).
    res = generate_combined_pattern_from_numbers([
        {"text": "Ihre Rechnung Nr. 1001", "number": "1001"},
        {"text": "Ihre Rechnung Nr. 2002", "number": "2002"},
    ])
    assert res["ok"] is True
    assert "(?:" not in res["pattern"]


# ───────────────────────── Fehlerfälle ─────────────────────────

def test_number_not_in_subject():
    res = generate_combined_pattern_from_numbers([
        {"text": "Ihre Rechnung Nr. 144853", "number": "999999"},
    ])
    assert res["ok"] is False
    assert res["error"]


def test_non_numeric_number_rejected():
    res = generate_combined_pattern_from_numbers([
        {"text": "Ihre Rechnung Nr. 144853", "number": "144A"},
    ])
    assert res["ok"] is False


def test_number_at_start_has_no_anchor():
    res = generate_combined_pattern_from_numbers([
        {"text": "144853 ist Ihre Rechnungsnummer", "number": "144853"},
    ])
    assert res["ok"] is False


def test_empty_examples_list():
    res = generate_combined_pattern_from_numbers([])
    assert res["ok"] is False


def test_one_bad_example_fails_whole_batch():
    # Zweites Beispiel ist kaputt → gesamte Erzeugung schlägt fehl,
    # damit kein halbes Pattern gespeichert wird.
    res = generate_combined_pattern_from_numbers([
        {"text": "Ihre Rechnung Nr. 1001", "number": "1001"},
        {"text": "Invoice number 2002", "number": "9999"},
    ])
    assert res["ok"] is False


# ───────────────────────── kind=zinv_id ─────────────────────────

def test_kind_zinv_id_uses_correct_group():
    res = generate_combined_pattern_from_numbers([
        {"text": "Folio ID 7788", "number": "7788"},
    ], group_name="zinv_id")
    assert res["ok"] is True
    assert "(?P<zinv_id>" in res["pattern"]
    assert _matches(res["pattern"], "Folio ID 7788", group="zinv_id") == "7788"
