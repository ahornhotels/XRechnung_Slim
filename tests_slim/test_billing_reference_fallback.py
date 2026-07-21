"""Tests fuer den BillingReference-Fallback bei Gutschriften (381).

Design: docs/superpowers/specs/2026-07-03-betriebs-haertung-design.md, Punkt 1.
Wenn ZINV_VOID_ZINV_ID fehlt, wird die Original-Rechnungsnummer aus dem
Zahlungs-Kommentar (ZPOS_COMMENT, Header-Feld paymentrefcomment) extrahiert,
gegen ZINV validiert und als billingreferenceid uebernommen.
"""
from pathlib import Path

from modules.invoice_fetcher import (
    _extract_number_candidates,
    _resolve_billing_reference_from_payment,
)


# ─────────────── _extract_number_candidates (reine Funktion) ───────────────

def test_candidates_none_und_leer():
    assert _extract_number_candidates(None) == []
    assert _extract_number_candidates("") == []
    assert _extract_number_candidates("   ") == []


def test_candidates_nur_ziffern():
    assert _extract_number_candidates("12345") == ["12345"]


def test_candidates_eingebettet_in_freitext():
    assert _extract_number_candidates("Storno zu RG 12345") == ["12345"]


def test_candidates_mehrere_folgen_laengste_zuerst():
    # Tie-Break gegen Streuzahlen wie Jahreszahlen: laengste Folge zuerst
    assert _extract_number_candidates("2024-98765") == ["98765", "2024"]


def test_candidates_gleiche_laenge_originalreihenfolge():
    assert _extract_number_candidates("111 222") == ["111", "222"]


def test_candidates_keine_ziffern():
    assert _extract_number_candidates("Storno ohne Nummer") == []


# ─────────────── _resolve_billing_reference_from_payment ───────────────

class FakeCursor:
    """Minimaler Cursor: liefert je zinv_number einen Treffer aus `known`."""

    def __init__(self, known: dict):
        self.known = known          # {"12345": ("12345", "2026-07-01")}
        self.queries = []           # aufgezeichnete (sql, params)
        self._last = None

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        self._last = self.known.get((params or {}).get("nr"))

    def fetchone(self):
        return self._last


def _header(comment, typecode="381", refid=None, own="GS-9999"):
    return {
        "id": own,
        "invoicetypecode": typecode,
        "billingreferenceid": refid,
        "paymentrefcomment": comment,
    }


def test_resolve_treffer_setzt_id_und_datum():
    cur = FakeCursor({"12345": ("12345", "2026-07-01")})
    header = _header("Storno zu RG 12345")
    _resolve_billing_reference_from_payment(cur, header)
    assert header["billingreferenceid"] == "12345"
    assert header["billingreferenceissuedate"] == "2026-07-01"


def test_resolve_kein_treffer_laesst_feld_leer():
    cur = FakeCursor({})
    header = _header("Storno zu RG 99999")
    _resolve_billing_reference_from_payment(cur, header)
    assert not header.get("billingreferenceid")
    assert not header.get("billingreferenceissuedate")


def test_resolve_leerer_kommentar_keine_db_abfrage():
    cur = FakeCursor({})
    header = _header(None)
    _resolve_billing_reference_from_payment(cur, header)
    assert cur.queries == []
    assert not header.get("billingreferenceid")


def test_resolve_mehrere_kandidaten_erster_gueltiger_gewinnt():
    # "2024" existiert nicht als Rechnung, "98765" schon -> laengster zuerst
    # probiert, Treffer gewinnt.
    cur = FakeCursor({"98765": ("98765", "2026-06-30")})
    header = _header("Gutschrift 2024-98765")
    _resolve_billing_reference_from_payment(cur, header)
    assert header["billingreferenceid"] == "98765"


def test_resolve_vorhandene_referenz_bleibt_unangetastet():
    # ZINV_VOID_ZINV_ID-Bezug hat Vorrang: Fallback greift nicht.
    cur = FakeCursor({"12345": ("12345", "2026-07-01")})
    header = _header("Kommentar 12345", refid="ORIG-1")
    _resolve_billing_reference_from_payment(cur, header)
    assert header["billingreferenceid"] == "ORIG-1"
    assert cur.queries == []


def test_resolve_nur_bei_gutschrift_381():
    # Normale Rechnung (380): Fallback greift nicht.
    cur = FakeCursor({"12345": ("12345", "2026-07-01")})
    header = _header("Kommentar 12345", typecode="380")
    _resolve_billing_reference_from_payment(cur, header)
    assert not header.get("billingreferenceid")
    assert cur.queries == []


def test_resolve_eigene_nummer_wird_uebersprungen():
    # Kommentar nennt die eigene Gutschrift-Nummer UND die echte Original.
    # Die eigene darf nicht als Selbstreferenz gewinnen.
    cur = FakeCursor({"77777": ("77777", "2026-06-01")})
    header = _header("Storno 12345 zu RG 77777", own="12345")
    _resolve_billing_reference_from_payment(cur, header)
    assert header["billingreferenceid"] == "77777"
    assert all((q[1] or {}).get("nr") != "12345" for q in cur.queries)


def test_resolve_nur_eigene_nummer_kein_bezug():
    cur = FakeCursor({"12345": ("12345", "2026-06-01")})
    header = _header("Gutschrift 12345", own="12345")
    _resolve_billing_reference_from_payment(cur, header)
    assert not header.get("billingreferenceid")


# ─────────────── SQL-Template ───────────────

def test_invoice_header_sql_liefert_paymentrefcomment():
    sql = (Path(__file__).resolve().parent.parent
           / "sql" / "invoice_header.sql").read_text(encoding="utf-8")
    assert "PaymentRefComment" in sql
    assert "zpos_comment" in sql.lower()
