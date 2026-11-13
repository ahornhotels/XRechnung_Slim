"""Tests: Rundungsausgleich je Steuersatz (hotel.json 'rundungsausgleich').

Befund (Feldrechnung 11/2026): SAP lehnt die XRechnung ab, KoSIT
meldet OK. Suite8 rundet die Steuer je Buchung (67 x Fruehstueck 3,85 brutto
-> je 0,61 Steuer, 3,24 netto). In BG-23 standen dann
  19 %: Bemessung 216,95 (Positionen 217,08), Steuer 40,87 (216,95 x 19 % = 41,22)
   7 %: Bemessung 8.339,55 (Positionen 8.339,54), Steuer 583,85 (8.339,55 x 7 % = 583,77)
KoSIT toleriert bei BR-S-08/BR-CO-17 +-1 EUR, SAP prueft exakt.

Loesung: je Steuersatz vom Brutto ausgehen (Endbetrag bleibt wie in Suite8),
Steuer = Brutto x Satz / (100 + Satz) einmal gerundet, Bemessung = Brutto -
Steuer. Den Rest zwischen Positionssumme und Bemessung traegt je nach
Einstellung
  "position": die groesste Position des Satzes,
  "abschlag": ein Abschlag/Zuschlag "Rundungsausgleich" je Satz (BG-20/21),
  "aus":      nichts (bisheriges Verhalten).
"""
from decimal import Decimal as D, ROUND_HALF_UP

import pytest
from lxml import etree

from modules import xml_builder
from tests_slim.test_creditnote_xsd import _base_invoice

NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}
C = D("0.01")


def _line(name, qty, price, pct):
    net = (D(qty) * D(price)).quantize(C)
    return {
        "invoicedquantity": str(qty),
        "lineextensionamount": str(net),
        "lineextensionamountnet": str(net),
        "priceamount": str(price),
        "itemname": name,
        "classifiedtaxcategoryid": "S",
        "classifiedtaxcategorypercent": f"{pct:.2f}",
    }


def _beispiel(mode=None):
    """Betraege wie in der abgelehnten Rechnung (zusammengefasste Positionen)."""
    inv = _base_invoice(0, billingreferenceid=None, billingreferenceissuedate=None,
                        prepaidamount="0.00", payableamount="9181.34")
    inv["lines"] = [
        _line("Fruehstueck", 67, "3.24", 19),
        _line("Fruehstueck 7", 69, "3.61", 7),
        _line("Getraenk", 67, "6.68", 7),
        _line("Uebernachtung", 51, "104.67", 7),
        _line("Uebernachtung DZ", 18, "128.04", 7),
    ]
    inv["tax_breakdown"] = [
        {"taxcategoryid": "S", "taxcategorypercent": "19.00",
         "taxableamount": "216.95", "taxamount": "40.87"},
        {"taxcategoryid": "S", "taxcategorypercent": "7.00",
         "taxableamount": "8339.55", "taxamount": "583.85"},
    ]
    inv["totals"] = {"invoicegross": 9181.34, "invoicenet": 8556.62,
                     "invoicetaxtotal": 624.72, "spay_cl": 9181.34}
    if mode is not None:
        inv["rundungsausgleich"] = mode
    return inv


def _doc(inv):
    return etree.fromstring(xml_builder.render(inv))


def _amt(node, path):
    return D(node.findtext(path, namespaces=NS))


def _groups(doc):
    out = {}
    for st in doc.findall("cac:TaxTotal/cac:TaxSubtotal", NS):
        pct = _amt(st, "cac:TaxCategory/cbc:Percent")
        out[pct] = (_amt(st, "cbc:TaxableAmount"), _amt(st, "cbc:TaxAmount"))
    return out


def _line_sums(doc):
    sums = {}
    for ln in doc.findall("cac:InvoiceLine", NS):
        pct = _amt(ln, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent")
        sums[pct] = sums.get(pct, D(0)) + _amt(ln, "cbc:LineExtensionAmount")
    return sums


def _ac(doc):
    """[(charge?, amount, percent, reason)] der Dokument-Zu-/Abschlaege."""
    return [(ac.findtext("cbc:ChargeIndicator", namespaces=NS) == "true",
             _amt(ac, "cbc:Amount"), _amt(ac, "cac:TaxCategory/cbc:Percent"),
             ac.findtext("cbc:AllowanceChargeReason", namespaces=NS))
            for ac in doc.findall("cac:AllowanceCharge", NS)]


def _total(doc, name):
    v = doc.findtext(f"cac:LegalMonetaryTotal/cbc:{name}", namespaces=NS)
    return D(v) if v is not None else D(0)


def _assert_strict_en16931(doc):
    """BR-S-08, BR-CO-17 (ohne KoSIT-Toleranz: max. 1 Cent), BR-CO-10..15."""
    lines = _line_sums(doc)
    acs = _ac(doc)
    for pct, (taxable, tax) in _groups(doc).items():
        expected = (lines.get(pct, D(0))
                    + sum((a for c, a, p, _ in acs if c and p == pct), D(0))
                    - sum((a for c, a, p, _ in acs if not c and p == pct), D(0)))
        assert taxable == expected, f"BR-S-08 {pct} %: {taxable} != {expected}"
        calc = (taxable * pct / 100).quantize(C, ROUND_HALF_UP)
        assert abs(tax - calc) <= C, f"BR-CO-17 {pct} %: {tax} vs {calc}"
    assert _total(doc, "LineExtensionAmount") == sum(lines.values(), D(0))
    assert _total(doc, "AllowanceTotalAmount") == sum((a for c, a, _, _ in acs if not c), D(0))
    assert _total(doc, "ChargeTotalAmount") == sum((a for c, a, _, _ in acs if c), D(0))
    assert _total(doc, "TaxExclusiveAmount") == (_total(doc, "LineExtensionAmount")
                                                 - _total(doc, "AllowanceTotalAmount")
                                                 + _total(doc, "ChargeTotalAmount"))
    tax_total = _amt(doc, "cac:TaxTotal/cbc:TaxAmount")
    assert tax_total == sum((t for _, t in _groups(doc).values()), D(0))
    assert _total(doc, "TaxInclusiveAmount") == _total(doc, "TaxExclusiveAmount") + tax_total


# ───────────────────────────── aus ─────────────────────────────

def test_aus_laesst_suite8_werte_stehen():
    for mode in (None, "aus"):
        doc = _doc(_beispiel(mode))
        assert _groups(doc)[D("19.00")] == (D("216.95"), D("40.87"))
        assert _ac(doc) == []


# ─────────────────────────── abschlag ──────────────────────────

def test_abschlag_rechnet_je_satz_vom_brutto():
    doc = _doc(_beispiel("abschlag"))
    assert _groups(doc) == {
        D("19.00"): (D("216.76"), D("41.19")),
        D("7.00"): (D("8339.62"), D("583.77")),
    }


def test_abschlag_weist_rest_als_zu_und_abschlag_aus():
    doc = _doc(_beispiel("abschlag"))
    assert sorted(_ac(doc)) == [
        (False, D("0.32"), D("19.00"), "Rundungsausgleich"),
        (True, D("0.08"), D("7.00"), "Rundungsausgleich"),
    ]
    assert _line_sums(doc) == {D("19.00"): D("217.08"), D("7.00"): D("8339.54")}


def test_abschlag_endbetrag_bleibt_wie_suite8():
    doc = _doc(_beispiel("abschlag"))
    assert _total(doc, "TaxInclusiveAmount") == D("9181.34")
    assert _total(doc, "PayableAmount") == D("9181.34")
    assert _amt(doc, "cac:TaxTotal/cbc:TaxAmount") == D("624.96")


def test_abschlag_erfuellt_en16931_ohne_toleranz():
    _assert_strict_en16931(_doc(_beispiel("abschlag")))


def test_abschlag_ist_xsd_gueltig():
    xml_builder.validate_xsd(xml_builder.render(_beispiel("abschlag")))


# ─────────────────────────── position ──────────────────────────

def test_position_traegt_rest_in_groesster_position():
    doc = _doc(_beispiel("position"))
    assert _ac(doc) == []
    assert _line_sums(doc) == {D("19.00"): D("216.76"), D("7.00"): D("8339.62")}
    nets = [_amt(ln, "cbc:LineExtensionAmount") for ln in doc.findall("cac:InvoiceLine", NS)]
    # 19 %: einzige Position; 7 %: groesste Position (51 x 104,67 = 5.338,17)
    assert nets == [D("216.76"), D("249.09"), D("447.56"), D("5338.25"), D("2304.72")]


def test_position_preis_passt_zur_menge():
    doc = _doc(_beispiel("position"))
    for ln in doc.findall("cac:InvoiceLine", NS):
        qty = _amt(ln, "cbc:InvoicedQuantity")
        price = _amt(ln, "cac:Price/cbc:PriceAmount")
        assert (qty * price).quantize(C, ROUND_HALF_UP) == _amt(ln, "cbc:LineExtensionAmount")


def test_position_erfuellt_en16931_ohne_toleranz():
    doc = _doc(_beispiel("position"))
    _assert_strict_en16931(doc)
    assert _total(doc, "TaxInclusiveAmount") == D("9181.34")
    assert _total(doc, "PayableAmount") == D("9181.34")


# ─────────────────────────── Randfaelle ─────────────────────────

@pytest.mark.parametrize("mode", ["position", "abschlag"])
def test_stimmige_rechnung_bleibt_unveraendert(mode):
    inv = _beispiel(mode)
    inv["lines"] = [_line("Uebernachtung", 1, "100.00", 7)]
    inv["tax_breakdown"] = [{"taxcategoryid": "S", "taxcategorypercent": "7.00",
                             "taxableamount": "100.00", "taxamount": "7.00"}]
    inv["totals"] = {"invoicegross": 107.0, "invoicenet": 100.0,
                     "invoicetaxtotal": 7.0, "spay_cl": 107.0}
    inv["header"]["payableamount"] = "107.00"
    doc = _doc(inv)
    assert _ac(doc) == []
    assert _groups(doc) == {D("7.00"): (D("100.00"), D("7.00"))}
    assert _total(doc, "PayableAmount") == D("107.00")


@pytest.mark.parametrize("mode", ["position", "abschlag"])
def test_vorausbezahlt_bleibt_zahlbetrag_null(mode):
    inv = _beispiel(mode)
    inv["header"]["prepaidamount"] = "9181.34"
    inv["header"]["payableamount"] = "0.00"
    doc = _doc(inv)
    assert _total(doc, "PrepaidAmount") == D("9181.34")
    assert _total(doc, "PayableAmount") == D("0.00")


@pytest.mark.parametrize("mode", ["position", "abschlag"])
def test_nullsteuer_gruppe_bleibt_unberuehrt(mode):
    inv = _beispiel(mode)
    city = _line("City Tax", 1, "12.50", 0)
    city["classifiedtaxcategoryid"] = "Z"
    inv["lines"].append(city)
    inv["totals"]["invoicegross"] = 9193.84
    inv["header"]["payableamount"] = "9193.84"
    doc = _doc(inv)
    assert _groups(doc)[D("0.00")] == (D("12.50"), D("0.00"))
    _assert_strict_en16931(doc)
    assert _total(doc, "PayableAmount") == D("9193.84")


@pytest.mark.parametrize("mode", ["position", "abschlag"])
def test_mit_storno_abschlag(mode):
    """Negative Zeile wird zum Abschlag (Split-Pfad); Ausgleich rechnet ihn mit."""
    inv = _beispiel(mode)
    storno = _line("Storno Fruehstueck", 1, "-3.24", 19)
    storno["vatparts"] = "-0.61"
    inv["lines"].append(storno)
    doc = _doc(inv)
    _assert_strict_en16931(doc)
    inv["rundungsausgleich"] = "aus"
    ohne = _doc(inv)
    assert _total(doc, "TaxInclusiveAmount") == _total(ohne, "TaxInclusiveAmount")
    assert _total(doc, "PayableAmount") == _total(ohne, "PayableAmount")


@pytest.mark.parametrize("mode", ["position", "abschlag"])
def test_gutschrift(mode):
    inv = _base_invoice(3)
    inv["rundungsausgleich"] = mode
    inv["lines"] = [_line("Storno Fruehstueck", -67, "3.24", 19)]
    inv["lines"][0]["priceamount"] = "-3.24"
    inv["tax_breakdown"] = [{"taxcategoryid": "S", "taxcategorypercent": "19.00",
                             "taxableamount": "-216.95", "taxamount": "-40.87"}]
    inv["totals"] = {"invoicegross": -257.95, "invoicenet": -217.08,
                     "invoicetaxtotal": -40.87, "spay_cl": -257.95}
    inv["header"]["payableamount"] = "-257.95"
    inv["header"]["prepaidamount"] = "0.00"
    root = etree.fromstring(xml_builder.render(inv))
    groups = {}
    for st in root.findall("cac:TaxTotal/cac:TaxSubtotal", NS):
        groups[_amt(st, "cac:TaxCategory/cbc:Percent")] = (
            _amt(st, "cbc:TaxableAmount"), _amt(st, "cbc:TaxAmount"))
    assert groups == {D("19.00"): (D("216.76"), D("41.19"))}
    assert _total(root, "TaxInclusiveAmount") == D("257.95")
    assert _total(root, "PayableAmount") == D("257.95")
    xml_builder.validate_xsd(xml_builder.render(inv), credit_note=True)


def test_unbekannter_modus_wirkt_wie_aus():
    doc = _doc(_beispiel("quatsch"))
    assert _groups(doc)[D("19.00")] == (D("216.95"), D("40.87"))


# ─────────────────────────── KoSIT ──────────────────────────────

@pytest.mark.parametrize("mode", ["position", "abschlag"])
def test_kosit_ohne_steuer_und_summenfehler(mode):
    from modules import kosit_validator
    try:
        kosit_validator.validate(xml_builder.render(_beispiel(mode)))
    except FileNotFoundError:
        pytest.skip("KoSIT nicht installiert")
    except kosit_validator.KositValidationError as e:
        relevant = [m for m in e.errors if any(r in str(m) for r in (
            "BR-S-", "BR-CO-", "BR-DEC-", "BR-33", "BR-36", "BR-37", "BR-38", "BR-41", "BR-42"))]
        assert relevant == []


# ─────────────────────────── Einstellung ────────────────────────

def test_einstellung_im_schema():
    from slim.core_slim import settings_schema as ss
    s = next(x for x in ss.section("inhalt").settings if x.key == "rundungsausgleich")
    assert s.file == "hotel.json" and s.type == "select"
    assert s.choices == ("aus", "position", "abschlag") == xml_builder.RUNDUNGSAUSGLEICH_MODI
    assert s.default == "aus"
    with pytest.raises(ss.SettingError):
        ss.coerce(s, "rest")


def test_fetcher_liest_einstellung(monkeypatch):
    from modules import invoice_fetcher
    for value, expected in ((None, "aus"), ("abschlag", "abschlag"), (" Position ", "position"),
                            ("quatsch", "aus"), (True, "aus")):
        monkeypatch.setattr(invoice_fetcher, "load_json",
                            lambda p, default=None, v=value: {} if v is None else {"rundungsausgleich": v})
        assert invoice_fetcher._rundungsausgleich() == expected, value


def test_fetcher_gibt_einstellung_an_die_rechnung():
    import inspect
    from modules import invoice_fetcher
    src = inspect.getsource(invoice_fetcher.fetch_invoice)
    assert '"rundungsausgleich": _rundungsausgleich()' in src
