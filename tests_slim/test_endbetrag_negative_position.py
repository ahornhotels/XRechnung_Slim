"""Endbetrag bleibt wie in Suite8, auch wenn die Rechnung eine negative
Position hat und der Builder die Steuer je Position neu aufbaut."""
import re
from decimal import Decimal as D

from modules import invoice_enrich as ie, xml_builder
from tests_slim.test_creditnote_xsd import _base_invoice


def _buchung(name, gross, pct=19):
    g = D(gross)
    tax = (g * pct / (100 + pct)).quantize(D("0.01"))   # wie sql/invoice_lines.sql
    return {"invoicedquantity": 1, "lineextensionamount": str(g),
            "lineextensionamountnet": str(g - tax), "priceamount": str(g - tax),
            "itemname": name, "itemcode": name, "classifiedtaxcategoryid": "S",
            "classifiedtaxcategorypercent": pct, "quantity": 1 if g > 0 else -1,
            "grossunitprice": abs(g), "postdate": "2026-11-01", "taxlinecount": 1,
            "ispaidout": 0}


def _xml(buchungen, bezahlt, modus="aus"):
    gross = sum(D(b["lineextensionamount"]) for b in buchungen)
    net = sum(D(b["lineextensionamountnet"]) for b in buchungen)
    inv = _base_invoice(0, billingreferenceid=None, billingreferenceissuedate=None,
                        prepaidamount=str(gross if bezahlt else D(0)),
                        payableamount=str(D(0) if bezahlt else gross))
    inv["lines"] = ie.group_lines(buchungen, True)
    inv["tax_breakdown"] = [{"taxcategoryid": "S", "taxcategorypercent": 19,
                             "taxableamount": str(net), "taxamount": str(gross - net)}]
    inv["totals"] = {"invoicegross": float(gross), "invoicenet": float(net),
                     "invoicetaxtotal": float(gross - net)}
    inv["rundungsausgleich"] = modus
    xml = xml_builder.render(inv).decode()
    return lambda tag: re.findall(rf"<cbc:{tag}[^>]*>([^<]+)<", xml)


def _getraenke_mit_rabatt():
    # 2,60 brutto: Steuer 0,42 (aus Brutto), aber 2,18 x 19 % = 0,41
    return [_buchung("Getraenk", "2.60") for _ in range(10)] + [_buchung("Rabatt", "-5.00")]


def test_vatparts_ist_die_steuer_aus_suite8():
    pos = ie.group_lines([_buchung("Getraenk", "2.60") for _ in range(10)], True)
    assert pos[0]["vatparts"] == "4.20"      # 10 x 0,42, nicht 10 x 0,41


def test_offene_rechnung_mit_rabatt_behaelt_endbetrag():
    g = _xml(_getraenke_mit_rabatt(), bezahlt=False)
    assert g("TaxInclusiveAmount") == ["21.00"]
    assert g("PayableAmount") == ["21.00"]
    assert g("TaxAmount")[0] == "3.40"


def test_bezahlte_rechnung_mit_rabatt_behaelt_vorauszahlung():
    g = _xml(_getraenke_mit_rabatt(), bezahlt=True)
    assert g("TaxInclusiveAmount") == ["21.00"]
    assert g("PrepaidAmount") == ["21.00"]
    assert g("PayableAmount") == ["0.00"]


def test_rundungsausgleich_aendert_endbetrag_nicht():
    for modus in ("abschlag", "position"):
        g = _xml(_getraenke_mit_rabatt(), bezahlt=False, modus=modus)
        assert g("TaxInclusiveAmount") == ["21.00"], modus
        assert g("PayableAmount") == ["21.00"], modus


def test_ohne_bruttobetrag_bleibt_netto_mal_satz():
    b = _buchung("Getraenk", "2.60")
    b["lineextensionamount"] = None
    assert ie.group_lines([b], True)[0]["vatparts"] == "0.41"


def test_anzahlungen_setzen_die_steuer_aus_suite8_ab():
    """Zwei Anzahlungen, ein Abschlag: Netto x Satz der Summe (149,35) weicht
    von der Summe der gebuchten Steuer (73,21 + 76,15 = 149,36) ab."""
    from tests_slim.test_deposit_allowances import _line, _invoice, ANZ_1, ANZ_2
    lines = [_line("Logis", 2401.80, 2244.67, 7),
             _line("Anzahlung", -1119.00, -1045.79, 7, deposit=ANZ_1),
             _line("Anzahlung", -1164.00, -1087.85, 7, deposit=ANZ_2)]
    xml = xml_builder.render(_invoice(lines, gross=118.80, net=111.03, tax=7.77)).decode()
    assert re.findall(r"<cbc:TaxInclusiveAmount[^>]*>([^<]+)<", xml) == ["118.80"]
