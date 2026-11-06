"""Tests: Positionen zusammenfassen und Gruppenrechnung je Gast und Zimmer."""
from decimal import Decimal
from pathlib import Path

from modules import invoice_enrich as ie
from modules.invoice_fetcher import _EXPECTED_OVERRIDE_MARKERS

SQL = (Path(__file__).resolve().parent.parent / "sql" / "invoice_lines.sql").read_text(encoding="utf-8")


def test_sql_liefert_menge_einzelpreis_buchungsdatum():
    for col in ("Quantity", "GrossUnitPrice", "PostDate"):
        assert f" {col}," in SQL or f" {col}\n" in SQL, col
    assert "z.zpos_quantity*decode(z.zpos_cdt,5,-1,1) Quantity" in SQL
    assert "GrossUnitPrice" in _EXPECTED_OVERRIDE_MARKERS["invoice_lines.sql"]


def _b(item="Logis", gross=107.00, net=100.00, pct=7, qty=1, unit=None, day="2026-03-02",
       yres=11, xcms=21, name="Erika Muster", room="101", deposit=None, code="LOG"):
    return {
        "itemname": item, "itemcode": code,
        "lineextensionamount": f"{gross:.2f}", "lineextensionamountnet": f"{net:.2f}",
        "priceamount": f"{net:.2f}", "invoicedquantity": "1",
        "classifiedtaxcategoryid": "S" if pct else "Z", "classifiedtaxcategorypercent": f"{pct:.2f}",
        "quantity": qty, "grossunitprice": unit if unit is not None else gross / (qty or 1),
        "postdate": day, "originyresid": yres, "originxcmsid": xcms, "originguestname": name,
        "originroom": room, "originarrival": "2026-03-01", "origindeparture": "2026-03-05",
        "depositzinvid": deposit, "depositinvoicenumber": None, "depositinvoicedate": None,
    }


def test_gleiche_buchungen_eine_position():
    lines = [_b(gross=33.34, net=31.16, day=d) for d in ("2026-03-02", "2026-03-03", "2026-03-04")]
    out = ie.group_lines(lines, merge=True)
    assert len(out) == 1
    p = out[0]
    assert p["invoicedquantity"] == "3" and p["lineextensionamountnet"] == "93.48"
    assert p["lineextensionamount"] == "100.02"
    assert (Decimal(p["invoicedquantity"]) * Decimal(p["priceamount"])).quantize(Decimal("0.01")) == Decimal("93.48")
    assert (p["periodstart"], p["periodend"]) == ("2026-03-02", "2026-03-04")
    assert p["vatparts"] == "6.54"   # 3 x round(31.16 * 7 %, 2) = 3 x 2.18


def test_anderer_preis_eigene_position():
    lines = [_b(), _b(day="2026-03-03"), _b(gross=128.40, net=120.00, day="2026-03-04")]
    out = ie.group_lines(lines, merge=True)
    assert [(p["invoicedquantity"], p["lineextensionamountnet"]) for p in out] == [("2", "200.00"), ("1", "120.00")]


def test_storno_nicht_verrechnet():
    lines = [_b(), _b(gross=-107.00, net=-100.00, qty=-1, unit=107.00)]
    out = ie.group_lines(lines, merge=True)
    assert sorted(p["lineextensionamountnet"] for p in out) == ["-100.00", "100.00"]


def test_anzahlung_bleibt_unangetastet():
    dep = _b(item="Deposit 7%", gross=-50.0, net=-46.73, deposit=4711)
    out = ie.group_lines([_b(), dep, dict(dep)], merge=True)
    assert sum(1 for p in out if p.get("depositzinvid")) == 2


def test_menge_null_oder_fehlend_menge_eins():
    a = _b(qty=0); b = _b(qty=None, item="Sauna")
    out = ie.group_lines([a, b], merge=True)
    assert all(p["invoicedquantity"] == "1" for p in out)
    assert all(p["priceamount"] == p["lineextensionamountnet"] for p in out)


def test_ein_gast_kein_positionstext():
    out = ie.group_lines([_b(), _b(item="Fruehstueck", code="FR")], merge=True)
    assert all(not p.get("note") and not p.get("guestlabel") for p in out)


def test_gruppe_positionstext_und_sortierung():
    lines = [_b(yres=1, xcms=1, name="Zoe Zehn", room="10"),
             _b(yres=2, xcms=2, name="Nina Neun", room="9"),
             _b(yres=3, xcms=3, name="Otto Ohne", room=None),
             _b(yres=4, xcms=4, name="Paul Pseudo", room="PM")]
    out = ie.group_lines(lines, merge=True)
    assert [p["note"] for p in out] == ["Zi. 9 · Nina Neun", "Zi. 10 · Zoe Zehn",
                                        "Zi. PM · Paul Pseudo", "Otto Ohne"]
    assert out[0]["guestlabel"] == "Zi. 9 · Nina Neun"


def test_konto_buchung_ohne_text():
    out = ie.group_lines([_b(yres=1, xcms=1), _b(yres=2, xcms=2, name="Max Beispiel"),
                          _b(item="Bankett", yres=None, xcms=55, name="Firma", room=None)], merge=True)
    bankett = next(p for p in out if p["itemname"] == "Bankett")
    assert not bankett.get("note")


def test_zusammenfassen_aus_nur_menge_und_zeitraum():
    lines = [_b(), _b(day="2026-03-03")]
    out = ie.group_lines(lines, merge=False)
    assert len(out) == 2 and out[0]["periodstart"] == out[0]["periodend"] == "2026-03-02"


def test_ohne_neue_spalten_unveraendert():
    old = {"itemname": "Logis", "lineextensionamountnet": "100.00", "priceamount": "100.00",
           "invoicedquantity": "1", "classifiedtaxcategoryid": "S", "classifiedtaxcategorypercent": "7.00"}
    out = ie.group_lines([dict(old), dict(old)], merge=True)
    assert len(out) == 2 and out[0]["invoicedquantity"] == "1"


def test_rechnungszeitraum_wird_erweitert():
    h = {"startdate": "2026-03-02", "enddate": "2026-03-05"}
    ie.extend_invoice_period(h, [{"periodstart": "2026-03-01", "periodend": "2026-03-03"},
                                 {"periodstart": "2026-03-04", "periodend": "2026-03-06"}])
    assert (h["startdate"], h["enddate"]) == ("2026-03-01", "2026-03-06")
    h2 = {}
    ie.extend_invoice_period(h2, [{"periodstart": "2026-03-01", "periodend": "2026-03-03"}])
    assert (h2["startdate"], h2["enddate"]) == ("2026-03-01", "2026-03-03")


def test_fetch_invoice_ruft_zusammenfassen():
    import inspect
    from modules import invoice_fetcher
    src = inspect.getsource(invoice_fetcher.fetch_invoice)
    assert "group_lines(lines, _positionen_zusammenfassen())" in src
    assert src.index("apply_auslagen_freigabe") < src.index("group_lines") < src.index("apply_guest_info")
    assert "extend_invoice_period(header, lines)" in src


def _rechnung(lines):
    from tests_slim.test_deposit_allowances import _invoice
    net = sum(Decimal(l["lineextensionamountnet"]) for l in lines)
    gross = sum(Decimal(l["lineextensionamount"]) for l in lines)
    return _invoice(lines, gross=float(gross), net=float(net), tax=float(gross - net))


def _bg23(inv):
    from lxml import etree
    from modules import xml_builder
    ns = {"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
          "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"}
    doc = etree.fromstring(xml_builder.render(inv))
    return doc, ns, sorted((s.findtext("cac:TaxCategory/cbc:Percent", namespaces=ns),
                            s.findtext("cbc:TaxableAmount", namespaces=ns),
                            s.findtext("cbc:TaxAmount", namespaces=ns))
                           for s in doc.findall("cac:TaxTotal/cac:TaxSubtotal", ns))


def test_vatparts_erhaelt_steuer_bei_abschlaegen():
    """Mit Abschlag rechnet der Builder die Steuer je Position neu. Das
    Zusammenfassen darf daran keinen Cent aendern."""
    # 3 x round(31.17 * 7 %, 2) = 6.54, aber round(93.51 * 7 %, 2) = 6.55
    lines = [_b(gross=33.35, net=31.17, day=d) for d in ("2026-03-02", "2026-03-03", "2026-03-04")]
    lines += [_b(item="Rabatt", gross=-10.70, net=-10.00, qty=-1, unit=10.70)]
    _, _, einzeln = _bg23(_rechnung([dict(l) for l in lines]))
    _, _, zusammen = _bg23(_rechnung(ie.group_lines([dict(l) for l in lines], merge=True)))
    assert zusammen == einzeln


def test_abschlagsgrund_nennt_gast_in_gruppe():
    lines = [_b(yres=1, xcms=1, room="101"), _b(yres=2, xcms=2, name="Max Beispiel", room="102"),
             _b(item="Rabatt", gross=-10.70, net=-10.00, qty=-1, unit=10.70, yres=2, xcms=2,
                name="Max Beispiel", room="102")]
    doc, ns, _ = _bg23(_rechnung(ie.group_lines(lines, merge=True)))
    reasons = [a.findtext("cbc:AllowanceChargeReason", namespaces=ns) for a in doc.findall("cac:AllowanceCharge", ns)]
    assert reasons == ["Rabatt · Zi. 102 · Max Beispiel"]


# --- Review zum Zusammenfassen ---

def test_z_mit_satz_traegt_keine_steuer():
    """Suite8 liefert Z mit Satz 19 (Steuerzeile mit Summe 0): keine Steuer in vatparts."""
    a = _b(gross=100.0, net=100.0, pct=19); a["classifiedtaxcategoryid"] = "Z"
    b = dict(a); b["postdate"] = "2026-03-03"
    rab = _b(item="Rabatt", gross=-20.0, net=-20.0, qty=-1, unit=20.0, pct=19); rab["classifiedtaxcategoryid"] = "Z"
    out = ie.group_lines([a, b, rab], merge=True)
    assert all(p.get("vatparts") in (None, "0.00") for p in out)
    _, _, groups = _bg23(_rechnung(out))
    assert all(tax == "0.00" for _, _, tax in groups)


def test_doppelt_negativ_ist_normale_buchung():
    """Live-Befund: Das Vorzeichen steckt in Menge ODER Preis; -1 x -107 ist
    eine Belastung ueber +107 und gehoert zur gleichen Position."""
    a = _b()                                                     # +1 x 107
    k = _b(gross=107.0, net=100.0, qty=-1, unit=-107.0, day="2026-03-03")   # -1 x -107 = +107
    out = ie.group_lines([a, k], merge=True)
    assert len(out) == 1 and out[0]["invoicedquantity"] == "2" and out[0]["priceamount"] == "100.0000"


def test_rueckgabe_ueber_negative_menge_eigene_position():
    """Pfand +1 x 10 und Rueckgabe -1 x 10: nicht verrechnet (Nutzervorgabe),
    die Rueckgabe hat Menge 1 mit Betrag -10 und positivem Preis."""
    out = ie.group_lines([_b(item="Pfand", gross=10.0, net=8.40, pct=19),
                          _b(item="Pfand", gross=-10.0, net=-8.40, pct=19, qty=-1, unit=10.0, day="2026-03-04")],
                         merge=True)
    assert sorted(p["lineextensionamountnet"] for p in out) == ["-8.40", "8.40"]
    neg = next(p for p in out if p["lineextensionamountnet"] == "-8.40")
    assert neg["invoicedquantity"] == "-1" and neg["priceamount"] == "8.4000"


def test_keine_einzelwerte_der_ersten_buchung_uebrig():
    lines = [dict(_b(), lineextensionamountvat="7.00", zposid=1),
             dict(_b(day="2026-03-03"), lineextensionamountvat="7.00", zposid=2)]
    p = ie.group_lines(lines, merge=True)[0]
    assert p["quantity"] == "2"
    for k in ("lineextensionamountvat", "zposid", "postdate"):
        assert k not in p, k


def test_zimmer_mit_sonderziffer_sortiert():
    out = ie.group_lines([_b(yres=1, xcms=1, room="²"), _b(yres=2, xcms=2, name="Max Beispiel", room="10")], merge=True)
    assert [p["originroom"] for p in out] == ["10", "²"]


def test_schalter_zusammenfassen_textwerte(monkeypatch):
    from modules import invoice_fetcher
    for value, expected in ((False, False), ("false", False), ("nein", False), (0, False), (True, True), (None, True)):
        monkeypatch.setattr(invoice_fetcher, "load_json",
                            lambda p, default=None, v=value: {} if v is None else {"positionen_zusammenfassen": v})
        assert invoice_fetcher._positionen_zusammenfassen() is expected, value
