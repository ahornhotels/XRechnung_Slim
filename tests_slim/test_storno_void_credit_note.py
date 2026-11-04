"""Tests: Suite8-Stornorechnung (ZINV_VOID_ZINV_ID gesetzt) -> CreditNote 381.

Befund an einer Live-DB (04.11.2026): Eine Stornorechnung traegt per ZPIL exakt
dieselben ZPOS wie das Original, mit POSITIVEN Betraegen (Netto, Steuer und
Brutto identisch zum Original). Ohne Auswertung von
ZINV_VOID_ZINV_ID wird sie als Invoice 380 gerendert, also als zweite Rechnung
(Duplikat) statt als Gutschrift.
"""
from lxml import etree

from modules import invoice_validator, xml_builder
from modules.invoice_fetcher import is_credit_note
from tests_slim.test_creditnote_xsd import _CN_XSD, _assert_xsd_valid, _base_invoice

_NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}


def _positive(inv: dict) -> dict:
    """Vorzeichen wie bei einem Suite8-VOID-Storno: alles positiv."""
    for ln in inv["lines"]:
        for k in ("lineextensionamount", "lineextensionamountnet", "priceamount"):
            ln[k] = ln[k].lstrip("-")
    for b in inv["tax_breakdown"]:
        for k in ("taxableamount", "taxamount"):
            b[k] = b[k].lstrip("-")
    inv["totals"] = {k: abs(float(v)) for k, v in inv["totals"].items()}
    return inv


def _void_storno(void_id=4711, **over):
    """Stornorechnung wie in Suite8: ROLE 0, SQL liefert '380', VOID gesetzt."""
    return _positive(_base_invoice(0, zinv_void_zinv_id=void_id, **over))


def test_void_storno_mit_positiven_betraegen_ist_gutschrift():
    assert is_credit_note(_void_storno()) is True


def test_ohne_void_bleibt_positive_rechnung_eine_rechnung():
    for leer in (None, "", 0, "0"):
        inv = _positive(_base_invoice(0, zinv_void_zinv_id=leer))
        assert is_credit_note(inv) is False, leer


def test_void_storno_rendert_creditnote_mit_bezug_und_positiven_betraegen():
    xml = xml_builder.render(_void_storno())
    doc = etree.fromstring(xml)
    assert etree.QName(doc).localname == "CreditNote"
    assert doc.findtext("cbc:CreditNoteTypeCode", namespaces=_NS) == "381"
    assert doc.findtext("cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID",
                        namespaces=_NS) == "RG-2026-0815"
    amounts = [float(e.text) for e in doc.iter()
               if e.text and etree.QName(e).localname.endswith("Amount")]
    assert amounts and all(a >= 0 for a in amounts)
    _assert_xsd_valid(xml, _CN_XSD)


def test_void_storno_einer_gutschrift_wird_geblockt():
    # Original war selbst eine Gutschrift (negative Summe). Der Storno dazu
    # waere fachlich eine Rechnung — nicht automatisch als Gutschrift senden.
    inv = _base_invoice(0, zinv_void_zinv_id=4711)   # negative Betraege
    issues = invoice_validator.validate(inv)
    assert any(i["field"] == "storno" and i["severity"] == "error" for i in issues)


def test_void_storno_normaler_rechnung_ohne_storno_fehler():
    issues = invoice_validator.validate(_void_storno())
    assert not any(i["field"] == "storno" for i in issues)
