"""Tests: Anzahlungen auf der Schlussrechnung (OPERA-Muster).

Befund an einer Live-DB (04.11.2026): Suite8 versteuert eine Anzahlung bei
Eingang auf einer eigenen Anzahlungsrechnung (ZINV_ROLE=1). Beim Check-in
bucht es auf das Gastfenster je Anzahlung ein NEGATIVES Paar aus
Anzahlungsartikel (CDT 1) und Steuer (CDT 2), beide mit
ZPOS_DEPOSIT_ZINV_ID = Anzahlungsrechnung. Eine Zahlungszeile gibt es auf der
Schlussrechnung nicht.

Ziel (§ 14 Abs. 5 Satz 2 UStG, wie OPERA): Leistung voll, je Steuersatz EIN
Abschlag auf Dokumentebene "Abzueglich Anzahlungsrechnung Nr. ... vom ...",
BG-3 je Anzahlungsrechnung. Eine voll angezahlte Rechnung (Endbetrag 0) ist
eine gueltige Rechnung, keine "aufgehobene Buchung"; ein Anzahlungsueberhang
ist keine Gutschrift.
"""
from pathlib import Path

from lxml import etree

from modules import invoice_validator, xml_builder
from modules.invoice_fetcher import _EXPECTED_OVERRIDE_MARKERS, is_credit_note
from tests_slim.test_creditnote_xsd import _INV_XSD, _assert_xsd_valid, _base_invoice

NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}
SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def _line(name, gross, net, pct, deposit=None):
    """Position wie aus invoice_lines.sql. deposit=(zinv_id, nr, datum)."""
    ln = {
        "invoicedquantity": "1",
        "lineextensionamount": f"{gross:.2f}",
        "lineextensionamountnet": f"{net:.2f}",
        "priceamount": f"{net:.2f}",
        "itemname": name,
        "classifiedtaxcategoryid": "S",
        "classifiedtaxcategorypercent": f"{pct:.2f}",
        "depositzinvid": None,
        "depositinvoicenumber": None,
        "depositinvoicedate": None,
    }
    if deposit:
        ln["depositzinvid"], ln["depositinvoicenumber"], ln["depositinvoicedate"] = deposit
    return ln


ANZ_1 = (90001, "100001", "2026-02-06")
ANZ_2 = (90002, "100002", "2026-05-27")


def _invoice(lines, gross, net, tax):
    """Schlussrechnung (ROLE 0) mit Totals wie aus invoice_totals.sql."""
    inv = _base_invoice(0, billingreferenceid=None, billingreferenceissuedate=None,
                        prepaidamount=None, payableamount=None)
    inv["lines"] = lines
    inv["tax_breakdown"] = [{"taxcategoryid": "S", "taxcategorypercent": "7.00",
                             "taxableamount": f"{net:.2f}", "taxamount": f"{tax:.2f}"}]
    inv["totals"] = {"invoicegross": gross, "invoicenet": net,
                     "invoicetaxtotal": tax, "spay_cl": 0}
    return inv


def _voll_angezahlt():
    """Zwei Anzahlungen zu 7 % decken die Uebernachtung exakt (Endbetrag 0)."""
    return _invoice([
        _line("Uebernachtung", 322.08, 301.01, 7),
        _line("Deposit 7%", -183.04, -171.07, 7, ANZ_2),
        _line("Deposit 7%", -139.04, -129.94, 7, ANZ_1),
    ], gross=0, net=0, tax=0)


def _render(inv):
    xml = xml_builder.render(inv)
    return xml, etree.fromstring(xml)


# ───────────────────────── Erkennung / Sperren ─────────────────────────

def test_anzahlungsueberhang_ist_keine_gutschrift():
    inv = _invoice([
        _line("Uebernachtung", 107.00, 100.00, 7),
        _line("Deposit 7%", -108.07, -101.00, 7, ANZ_1),
    ], gross=-1.07, net=-1.00, tax=-0.07)
    assert is_credit_note(inv) is False


def test_echte_gutschrift_ohne_anzahlung_bleibt_gutschrift():
    inv = _invoice([_line("Uebernachtung", -107.00, -100.00, 7)],
                   gross=-107.00, net=-100.00, tax=-7.00)
    assert is_credit_note(inv) is True


def test_voll_angezahlte_rechnung_wird_nicht_geblockt():
    issues = invoice_validator.validate(_voll_angezahlt())
    # Stammdatenluecken des Test-Headers (z. B. Kunden-E-Mail) sind hier egal.
    relevant = {"totals.net", "deposit", "storno", "billing_reference", "lines"}
    assert not [i for i in issues if i["field"] in relevant], issues


def test_aufgehobene_buchung_ohne_anzahlung_bleibt_geblockt():
    inv = _invoice([
        _line("Pfand", 10.70, 10.00, 7),
        _line("Pfand zurueck", -10.70, -10.00, 7),
    ], gross=0, net=0, tax=0)
    issues = invoice_validator.validate(inv)
    assert any(i["field"] == "totals.net" for i in issues)


def test_anzahlung_ohne_rechnungsnummer_wird_geblockt():
    inv = _voll_angezahlt()
    inv["lines"][1]["depositinvoicenumber"] = None
    issues = invoice_validator.validate(inv)
    assert any(i["field"] == "deposit" and i["severity"] == "error" for i in issues)


def test_anzahlung_mit_plus_ueberhang_je_satz_wird_geblockt():
    # Mehr Anzahlung zurueckgebucht als abgezogen: kein Abschlag ableitbar.
    inv = _invoice([
        _line("Uebernachtung", 107.00, 100.00, 7),
        _line("Deposit 7%", 21.40, 20.00, 7, ANZ_1),
    ], gross=128.40, net=120.00, tax=8.40)
    issues = invoice_validator.validate(inv)
    assert any(i["field"] == "deposit" and i["severity"] == "error" for i in issues)


# ───────────────────────── Rendering ─────────────────────────

def test_voll_angezahlt_rendert_rechnung_mit_abschlag_und_bezuegen():
    xml, doc = _render(_voll_angezahlt())
    assert etree.QName(doc).localname == "Invoice"
    assert doc.findtext("cbc:InvoiceTypeCode", namespaces=NS) == "380"

    # Nur die Leistung als Position, Anzahlung nicht als Position
    names = [e.text for e in doc.findall("cac:InvoiceLine/cac:Item/cbc:Name", NS)]
    assert names == ["Uebernachtung"]

    # Genau ein Abschlag fuer 7 % ueber die Summe beider Anzahlungen
    acs = doc.findall("cac:AllowanceCharge", NS)
    assert len(acs) == 1
    assert acs[0].findtext("cbc:ChargeIndicator", namespaces=NS) == "false"
    assert acs[0].findtext("cbc:Amount", namespaces=NS) == "301.01"
    assert acs[0].findtext("cac:TaxCategory/cbc:Percent", namespaces=NS) == "7.00"
    reason = acs[0].findtext("cbc:AllowanceChargeReason", namespaces=NS)
    assert reason.startswith("Abzüglich Anzahlungsrechnung")
    assert "Nr. 100001 vom 06.02.2026" in reason and "Nr. 100002 vom 27.05.2026" in reason

    # BG-3 je Anzahlungsrechnung
    refs = {(r.findtext("cac:InvoiceDocumentReference/cbc:ID", namespaces=NS),
             r.findtext("cac:InvoiceDocumentReference/cbc:IssueDate", namespaces=NS))
            for r in doc.findall("cac:BillingReference", NS)}
    assert refs == {("100001", "2026-02-06"), ("100002", "2026-05-27")}

    # BG-23: 7-%-Gruppe bleibt als 0/0 stehen (Position + Abschlag nutzen sie)
    subs = doc.findall("cac:TaxTotal/cac:TaxSubtotal", NS)
    assert [(s.findtext("cac:TaxCategory/cbc:Percent", namespaces=NS),
             s.findtext("cbc:TaxableAmount", namespaces=NS),
             s.findtext("cbc:TaxAmount", namespaces=NS)) for s in subs] == [("7.00", "0.00", "0.00")]

    lmt = doc.find("cac:LegalMonetaryTotal", NS)
    assert lmt.findtext("cbc:LineExtensionAmount", namespaces=NS) == "301.01"
    assert lmt.findtext("cbc:AllowanceTotalAmount", namespaces=NS) == "301.01"
    assert lmt.findtext("cbc:TaxInclusiveAmount", namespaces=NS) == "0.00"
    assert lmt.findtext("cbc:PayableAmount", namespaces=NS) == "0.00"
    _assert_xsd_valid(xml, _INV_XSD)


def test_storno_einer_anzahlung_hebt_sich_auf():
    # A abgezogen, B abgezogen, B-Storno (C) wieder dazu: nur A bleibt.
    anz_b, anz_c = (90003, "100003", "2026-09-10"), (90004, "100004", "2026-09-10")
    inv = _invoice([
        _line("Uebernachtung", 107.00, 100.00, 7),
        _line("Deposit 7%", -53.50, -50.00, 7, ANZ_1),
        _line("Deposit 7%", -42.80, -40.00, 7, anz_b),
        _line("Deposit 7%", 42.80, 40.00, 7, anz_c),
    ], gross=53.50, net=50.00, tax=3.50)
    _, doc = _render(inv)
    acs = doc.findall("cac:AllowanceCharge", NS)
    assert [a.findtext("cbc:Amount", namespaces=NS) for a in acs] == ["50.00"]
    assert "Nr. 100001 vom 06.02.2026" in acs[0].findtext("cbc:AllowanceChargeReason", namespaces=NS)
    assert "100003" not in acs[0].findtext("cbc:AllowanceChargeReason", namespaces=NS)
    refs = [r.findtext("cac:InvoiceDocumentReference/cbc:ID", namespaces=NS)
            for r in doc.findall("cac:BillingReference", NS)]
    assert refs == ["100001"]
    assert not [n for n in doc.findall("cac:InvoiceLine/cac:Item/cbc:Name", NS)
                if n.text.startswith("Deposit")]


def test_anzahlungen_mit_zwei_saetzen_ergeben_zwei_abschlaege():
    inv = _invoice([
        _line("Uebernachtung", 214.00, 200.00, 7),
        _line("Fruehstueck", 119.00, 100.00, 19),
        _line("Deposit 7%", -107.00, -100.00, 7, ANZ_1),
        _line("Deposit 19%", -59.50, -50.00, 19, ANZ_2),
    ], gross=166.50, net=150.00, tax=16.50)
    _, doc = _render(inv)
    got = sorted((a.findtext("cac:TaxCategory/cbc:Percent", namespaces=NS),
                  a.findtext("cbc:Amount", namespaces=NS))
                 for a in doc.findall("cac:AllowanceCharge", NS))
    assert got == [("19.00", "50.00"), ("7.00", "100.00")]


def test_rechnung_ohne_anzahlung_hat_keinen_bezug():
    inv = _invoice([_line("Uebernachtung", 107.00, 100.00, 7)],
                   gross=107.00, net=100.00, tax=7.00)
    _, doc = _render(inv)
    assert doc.findall("cac:BillingReference", NS) == []
    assert doc.findall("cac:AllowanceCharge", NS) == []


# ───────────────────────── SQL ─────────────────────────

def test_positions_sql_liefert_anzahlungsbezug():
    sql = (SQL_DIR / "invoice_lines.sql").read_text(encoding="utf-8")
    for col in ("DepositZinvId", "DepositInvoiceNumber", "DepositInvoiceDate"):
        assert col in sql, col
    assert "zpos_deposit_zinv_id" in sql.lower()


def test_veralteter_positions_override_wird_erkannt():
    assert "DepositZinvId" in _EXPECTED_OVERRIDE_MARKERS.get("invoice_lines.sql", ())


# ───────────────────────── Randfaelle aus der Live-DB ─────────────────────────

def test_nur_anzahlungen_ohne_leistung_wird_geblockt():
    # Erstattung/Ausbuchung einer Anzahlung: kein Abschlag ohne Leistung.
    inv = _invoice([_line("Deposit 7%", -107.00, -100.00, 7, ANZ_1)],
                   gross=-107.00, net=-100.00, tax=-7.00)
    issues = invoice_validator.validate(inv)
    assert any(i["field"] == "deposit" and i["severity"] == "error" for i in issues)


def test_void_storno_mit_anzahlungszeilen_wird_geblockt():
    inv = _voll_angezahlt()
    inv["header"]["zinv_void_zinv_id"] = 4711
    issues = invoice_validator.validate(inv)
    assert any(i["field"] == "deposit" and i["severity"] == "error" for i in issues)


class _Cursor:
    """Cursor, der die Anzahlungsspalte nicht kennt (aeltere Suite8-Version)."""

    def __init__(self):
        self.sqls = []
        self.description = [("ITEMNAME",)]

    def execute(self, sql, params=None):
        self.sqls.append(sql)
        if "zpos_deposit_zinv_id" in sql.lower():
            raise Exception('ORA-00904: "Z"."ZPOS_DEPOSIT_ZINV_ID": invalid identifier')

    def fetchall(self):
        return [("Uebernachtung",)]


def test_positions_sql_faellt_ohne_anzahlungsspalte_zurueck(monkeypatch):
    from modules import invoice_fetcher
    monkeypatch.setattr(invoice_fetcher, "_missing_line_columns", set())
    cur = _Cursor()
    lines = invoice_fetcher._fetch_lines(cur, 1)
    assert lines == [{"itemname": "Uebernachtung"}]
    assert len(cur.sqls) == 2 and "zpos_deposit_zinv_id" not in cur.sqls[1].lower()
    # Danach direkt die Variante ohne Spalte, kein erneuter Fehlversuch
    cur2 = _Cursor()
    invoice_fetcher._fetch_lines(cur2, 2)
    assert len(cur2.sqls) == 1


def test_andere_datenbankfehler_werden_nicht_verschluckt(monkeypatch):
    import pytest
    from modules import invoice_fetcher
    monkeypatch.setattr(invoice_fetcher, "_missing_line_columns", set())

    class _Kaputt(_Cursor):
        def execute(self, sql, params=None):
            raise Exception("ORA-03113: end-of-file on communication channel")

    with pytest.raises(Exception, match="ORA-03113"):
        invoice_fetcher._fetch_lines(_Kaputt(), 1)


def test_gutschrift_mit_anzahlungszeilen_wird_geblockt():
    inv = _invoice([
        _line("Uebernachtung", -107.00, -100.00, 7),
        _line("Deposit 7%", -53.50, -50.00, 7, ANZ_1),
    ], gross=-160.50, net=-150.00, tax=-10.50)
    issues = invoice_validator.validate(inv)
    assert any(i["field"] == "deposit" and i["severity"] == "error" for i in issues)
