"""Tests fuer die BG-23-Abgleich-Logik (BR-Z-01 und Verwandte).

Hintergrund (Feld-Vorfall zinv=739759): Buchungen mit 0 % MwSt — typisch
CityTax/Kurtaxe — erzeugen in Suite8 KEINE Steuerbuchung (ZPOS_CDT=2).
Daraus folgt eine Inkonsistenz zwischen den beiden SQL-Quellen:

* ``sql/invoice_lines.sql`` leitet die Positions-Kategorie aus der Steuer-
  summe je TAXLINK ab: keine Steuerbuchung → ``NVL(...,0)=0`` → ``Z``.
* ``sql/invoice_tax.sql`` baut die Aufschluesselung ausschliesslich AUS
  Steuerbuchungen (``WHERE z.ZPOS_CDT IN (2)``) — fuer den 0-%-Code
  entsteht dort also gar keine Gruppe.

Ergebnis: Position traegt ``Z``, BG-23 enthaelt kein ``Z`` → KoSIT lehnt
mit BR-Z-01 ab ("shall contain ... exactly one VAT category code equal
with 'Zero rated'").
"""
from decimal import Decimal

from lxml import etree

from modules import xml_builder

NS = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}

_HEADER = {
    "id": "739759",
    "issuedate": "2026-09-01",
    "documentcurrencycode": "EUR",
    "prepaidamount": "0",
    "payableamount": "0",
}


def _line(name, net, cat, pct, gross=None):
    gross = net if gross is None else gross
    return {
        "itemname": name,
        "invoicedquantity": "1",
        "priceamount": str(net),
        "lineextensionamount": str(gross),
        "lineextensionamountnet": str(net),
        "classifiedtaxcategoryid": cat,
        "classifiedtaxcategorypercent": pct,
    }


def _render(invoice):
    return etree.fromstring(xml_builder.render(invoice))


def _breakdown(root):
    """[(category, percent, taxable, tax)] aus BG-23."""
    out = []
    for st in root.findall(".//cac:TaxTotal/cac:TaxSubtotal", NS):
        out.append((
            st.findtext("cac:TaxCategory/cbc:ID", namespaces=NS),
            st.findtext("cac:TaxCategory/cbc:Percent", namespaces=NS),
            st.findtext("cbc:TaxableAmount", namespaces=NS),
            st.findtext("cbc:TaxAmount", namespaces=NS),
        ))
    return out


def test_citytax_z_line_erzeugt_fehlenden_z_eintrag_in_bg23():
    """BR-Z-01: Z-Position ohne Z-Gruppe in BG-23 (der Feld-Vorfall)."""
    invoice = {
        "header": dict(_HEADER),
        "lines": [
            _line("Uebernachtung", "100.00", "S", 7, gross="107.00"),
            _line("CityTax", "20.00", "Z", 0),
        ],
        # Suite8 liefert nur die Gruppe des 7-%-Steuercodes.
        "tax_breakdown": [
            {"taxcategoryid": "S", "taxcategorypercent": 7,
             "taxableamount": "100.00", "taxamount": "7.00"},
        ],
        "totals": {"invoicenet": "120.00", "invoicegross": "127.00",
                   "invoicetaxtotal": "7.00"},
    }
    rows = _breakdown(_render(invoice))
    z_rows = [r for r in rows if r[0] == "Z"]
    assert len(z_rows) == 1, f"genau eine Z-Gruppe erwartet, BG-23={rows}"
    _, pct, taxable, tax = z_rows[0]
    assert Decimal(pct) == 0          # BR-Z-08
    assert Decimal(taxable) == Decimal("20.00")   # BR-Z-08: Summe der Z-Nettos
    assert Decimal(tax) == 0          # BR-Z-06


def test_mehrere_z_gruppen_werden_zu_genau_einer_zusammengefasst():
    """BR-Z-01 verlangt *exactly one* — zwei 0-%-Steuercodes duerfen nicht
    zwei Z-Zeilen erzeugen."""
    invoice = {
        "header": dict(_HEADER),
        "lines": [
            _line("CityTax", "50.00", "Z", 0),
            _line("Durchlaufender Posten", "30.00", "Z", 0),
        ],
        "tax_breakdown": [
            {"taxcategoryid": "Z", "taxcategorypercent": 0,
             "taxableamount": "50.00", "taxamount": "0.00"},
            {"taxcategoryid": "Z", "taxcategorypercent": 0,
             "taxableamount": "30.00", "taxamount": "0.00"},
        ],
        "totals": {"invoicenet": "80.00", "invoicegross": "80.00",
                   "invoicetaxtotal": "0.00"},
    }
    rows = _breakdown(_render(invoice))
    z_rows = [r for r in rows if r[0] == "Z"]
    assert len(z_rows) == 1, f"genau eine Z-Gruppe erwartet, BG-23={rows}"
    assert Decimal(z_rows[0][2]) == Decimal("80.00")


def test_zwei_s_gruppen_gleichen_satzes_werden_zusammengefasst():
    """BR-S-01/BR-S-08 analog: zwei ZTCDs mit 7 % ergeben eine Gruppe.
    Summen bleiben erhalten (keine Doppelzaehlung, BR-CO-14)."""
    invoice = {
        "header": dict(_HEADER),
        "lines": [
            _line("Uebernachtung", "100.00", "S", 7, gross="107.00"),
            _line("Fruehstueck", "50.00", "S", 7, gross="53.50"),
        ],
        "tax_breakdown": [
            {"taxcategoryid": "S", "taxcategorypercent": 7,
             "taxableamount": "100.00", "taxamount": "7.00"},
            {"taxcategoryid": "S", "taxcategorypercent": 7,
             "taxableamount": "50.00", "taxamount": "3.50"},
        ],
        "totals": {"invoicenet": "150.00", "invoicegross": "160.50",
                   "invoicetaxtotal": "10.50"},
    }
    rows = _breakdown(_render(invoice))
    s_rows = [r for r in rows if r[0] == "S"]
    assert len(s_rows) == 1, f"genau eine S/7-Gruppe erwartet, BG-23={rows}"
    assert Decimal(s_rows[0][2]) == Decimal("150.00")
    assert Decimal(s_rows[0][3]) == Decimal("10.50")


def test_unterschiedliche_s_saetze_bleiben_getrennt():
    """Regressionsschutz: 7 % und 19 % duerfen NICHT verschmolzen werden."""
    invoice = {
        "header": dict(_HEADER),
        "lines": [
            _line("Uebernachtung", "100.00", "S", 7, gross="107.00"),
            _line("Minibar", "100.00", "S", 19, gross="119.00"),
        ],
        "tax_breakdown": [
            {"taxcategoryid": "S", "taxcategorypercent": 7,
             "taxableamount": "100.00", "taxamount": "7.00"},
            {"taxcategoryid": "S", "taxcategorypercent": 19,
             "taxableamount": "100.00", "taxamount": "19.00"},
        ],
        "totals": {"invoicenet": "200.00", "invoicegross": "226.00",
                   "invoicetaxtotal": "26.00"},
    }
    rows = _breakdown(_render(invoice))
    assert sorted(Decimal(r[1]) for r in rows) == [Decimal(7), Decimal(19)]


def test_phantom_gruppe_ohne_passende_position_bleibt_gefiltert():
    """Der 0/0-Filter (BR-CO-17) darf nicht ausgehebelt werden: eine
    Suite8-Phantomgruppe, die keine Position verwendet, bleibt draussen."""
    invoice = {
        "header": dict(_HEADER),
        "lines": [_line("Uebernachtung", "100.00", "S", 7, gross="107.00")],
        "tax_breakdown": [
            {"taxcategoryid": "S", "taxcategorypercent": 7,
             "taxableamount": "100.00", "taxamount": "7.00"},
            {"taxcategoryid": "Z", "taxcategorypercent": 0,
             "taxableamount": "0.00", "taxamount": "0.00"},
        ],
        "totals": {"invoicenet": "100.00", "invoicegross": "107.00",
                   "invoicetaxtotal": "7.00"},
    }
    rows = _breakdown(_render(invoice))
    assert [r[0] for r in rows] == ["S"], f"BG-23={rows}"


def test_z_kategorie_aus_allowance_erzeugt_z_eintrag():
    """BR-Z-01 nennt auch BG-20/BG-21: eine negative Z-Zeile wird zur
    Allowance — die Z-Gruppe muss trotzdem in BG-23 stehen."""
    invoice = {
        "header": dict(_HEADER),
        "lines": [
            _line("Uebernachtung", "100.00", "S", 7, gross="107.00"),
            _line("CityTax-Erstattung", "-20.00", "Z", 0, gross="-20.00"),
        ],
        "tax_breakdown": [
            {"taxcategoryid": "S", "taxcategorypercent": 7,
             "taxableamount": "100.00", "taxamount": "7.00"},
        ],
        "totals": {"invoicenet": "80.00", "invoicegross": "87.00",
                   "invoicetaxtotal": "7.00"},
    }
    root = _render(invoice)
    al_cats = [e.text for e in root.findall(
        "./cac:AllowanceCharge/cac:TaxCategory/cbc:ID", NS)]
    assert "Z" in al_cats, "negative Z-Zeile sollte Allowance werden"
    z_rows = [r for r in _breakdown(root) if r[0] == "Z"]
    assert len(z_rows) == 1, "BG-23 braucht genau eine Z-Gruppe"


def test_gutschrift_mit_z_position_bekommt_z_eintrag():
    """Auch der CreditNote-Pfad muss BR-Z-01 erfuellen."""
    invoice = {
        "header": dict(_HEADER),
        "lines": [
            _line("Uebernachtung", "-100.00", "S", 7, gross="-107.00"),
            _line("CityTax", "-20.00", "Z", 0, gross="-20.00"),
        ],
        "tax_breakdown": [
            {"taxcategoryid": "S", "taxcategorypercent": 7,
             "taxableamount": "-100.00", "taxamount": "-7.00"},
        ],
        "totals": {"invoicenet": "-120.00", "invoicegross": "-127.00",
                   "invoicetaxtotal": "-7.00"},
    }
    rows = _breakdown(_render(invoice))
    z_rows = [r for r in rows if r[0] == "Z"]
    assert len(z_rows) == 1, f"genau eine Z-Gruppe erwartet, BG-23={rows}"
    assert Decimal(z_rows[0][2]) == Decimal("20.00")   # positiv im CreditNote
