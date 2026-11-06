"""Tests: Kaeuferadresse aus Strasse 1/2/3 (BT-50, BT-51, BT-163).

Suite8 kennt drei Strassenzeilen (XADR_STREET1..3). Es kommt vor, dass Zeile 1
leer und Zeile 2 gefuellt ist. Leere Zeilen fallen weg, die uebrigen ruecken
nach oben: 1. -> StreetName, 2. -> AdditionalStreetName, 3. -> AddressLine.
"""
import pytest
from lxml import etree

from modules import invoice_enrich as ie
from modules import xml_builder
from tests_slim.test_deposit_allowances import _invoice, _line
from tests_slim.test_creditnote_xsd import _CN_XSD, _INV_XSD, _assert_xsd_valid, _base_invoice

NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}


def test_leere_zeilen_ruecken_nach_oben():
    assert ie.street_lines(None, "Hinterhaus", "  ") == ["Hinterhaus"]
    assert ie.street_lines("", "Postfach 1", "Etage 3") == ["Postfach 1", "Etage 3"]
    assert ie.street_lines(" Kundenweg 2 ", None, None) == ["Kundenweg 2"]


def test_drei_zeilen_auf_bt50_51_163():
    h = {"customeradrstreet1": "Kundenweg 2", "customeradrstreet2": "Haus B",
         "customeradrstreet3": "c/o Einkauf", "customerstreetname": "Kundenweg 2"}
    ie.apply_customer_address(h)
    assert (h["customerstreetname"], h["customeradditionalstreetname"],
            h["customeraddressline"]) == ("Kundenweg 2", "Haus B", "c/o Einkauf")


def test_zeile1_leer_zeile2_wird_strasse():
    h = {"customeradrstreet1": "  ", "customeradrstreet2": "Am Markt 5",
         "customeradrstreet3": None, "customerstreetname": "Primaerweg 9"}
    ie.apply_customer_address(h)
    assert h["customerstreetname"] == "Am Markt 5"
    assert h["customeradditionalstreetname"] is None
    assert h["customeraddressline"] is None


def test_rechnungsadresse_leer_nimmt_primaeradresse():
    h = {"customeradrstreet1": None, "customeradrstreet2": None, "customeradrstreet3": None,
         "customerprimstreet1": None, "customerprimstreet2": "Am Markt 5",
         "customerprimstreet3": None, "customerstreetname": None}
    ie.apply_customer_address(h)
    assert h["customerstreetname"] == "Am Markt 5"
    assert h["customeradditionalstreetname"] is None


def test_alles_leer_strasse_bleibt_unveraendert():
    h = {"customeradrstreet1": None, "customeradrstreet2": "", "customeradrstreet3": None,
         "customerprimstreet1": None, "customerprimstreet2": None,
         "customerprimstreet3": None, "customerstreetname": None}
    ie.apply_customer_address(h)
    assert h["customerstreetname"] is None


def test_ohne_neue_spalten_bleibt_alles_wie_bisher():
    """SQL-Override ohne die neuen Spalten: Verhalten wie vor dem Umbau."""
    h = {"customerstreetname": "Kundenweg 2"}
    ie.apply_customer_address(h)
    assert h["customerstreetname"] == "Kundenweg 2"
    assert h.get("customeradditionalstreetname") is None


def _doc(role, **header):
    """role 0: positive Rechnung (Invoice), role 3: Gutschrift (CreditNote)."""
    if role == 0:
        inv = _invoice([_line("Uebernachtung", 107.00, 100.00, 7)], gross=107.00, net=100.00, tax=7.00)
    else:
        inv = _base_invoice(3)
    inv["header"].update(header)
    return inv


def _customer_address(xml: bytes):
    doc = etree.fromstring(xml)
    return doc.find("cac:AccountingCustomerParty/cac:Party/cac:PostalAddress", NS)


@pytest.mark.parametrize("role,xsd", [(0, _INV_XSD), (3, _CN_XSD)])
def test_xml_zusatz_ohne_adresszeile(role, xsd):
    inv = _doc(role, customeradditionalstreetname="Haus B", customeraddressline=None)
    xml = xml_builder.render(inv)
    adr = _customer_address(xml)
    assert adr.findtext("cbc:AdditionalStreetName", namespaces=NS) == "Haus B"
    assert adr.find("cac:AddressLine", NS) is None
    _assert_xsd_valid(xml, xsd)


@pytest.mark.parametrize("role,xsd", [(0, _INV_XSD), (3, _CN_XSD)])
def test_xml_adresszeile_nach_plz_vor_land(role, xsd):
    inv = _doc(role, customeradditionalstreetname="Haus B",
                        customeraddressline="c/o Einkauf & Co")
    xml = xml_builder.render(inv)
    adr = _customer_address(xml)
    tags = [etree.QName(el).localname for el in adr]
    assert tags == ["StreetName", "AdditionalStreetName", "CityName", "PostalZone",
                    "AddressLine", "Country"]
    assert adr.findtext("cac:AddressLine/cbc:Line", namespaces=NS) == "c/o Einkauf & Co"
    _assert_xsd_valid(xml, xsd)


@pytest.mark.parametrize("role", [0, 3])
def test_xml_ohne_zusatz_keine_leeren_elemente(role):
    xml = xml_builder.render(_doc(role))
    adr = _customer_address(xml)
    assert adr.find("cbc:AdditionalStreetName", NS) is None
    assert adr.find("cac:AddressLine", NS) is None


def test_header_sql_liefert_drei_strassenzeilen_und_marker():
    from pathlib import Path
    from modules.invoice_fetcher import _EXPECTED_OVERRIDE_MARKERS
    sql = (Path(__file__).resolve().parent.parent / "sql" / "invoice_header.sql").read_text(encoding="utf-8")
    for col in ("CustomerAdrStreet1", "CustomerAdrStreet2", "CustomerAdrStreet3",
                "CustomerPrimStreet1", "CustomerPrimStreet2", "CustomerPrimStreet3"):
        assert col in sql
    assert "xadr_street3" in sql.lower()
    assert "CustomerAdrStreet2" in _EXPECTED_OVERRIDE_MARKERS["invoice_header.sql"]




# --- Review-Fixes: eine Adressquelle je Adresse, Overrides, echte Integration ---

def test_rechnungsadresse_ohne_strasse_nimmt_primaerstrasse_wie_bisher():
    """Live-Befund: tausende Rechnungsadressen haben keine Strasse. Bisher fuellte
    das SQL (nvl) die Strasse aus der Primaeradresse - das darf nicht wegfallen,
    sonst werden diese Rechnungen geblockt."""
    h = {"customeradrid": 7, "customeradrstreet1": "  ", "customeradrstreet2": None,
         "customeradrstreet3": None, "customerprimstreet1": "Primaerweg 9",
         "customerprimstreet2": None, "customerprimstreet3": None,
         "customerstreetname": "Primaerweg 9"}
    ie.apply_customer_address(h)
    assert h["customerstreetname"] == "Primaerweg 9"


def test_rechnungsadresse_mit_strasse_mischt_keine_primaerzeilen():
    h = {"customeradrid": 7, "customeradrstreet1": "Kundenweg 2", "customeradrstreet2": None,
         "customeradrstreet3": None, "customerprimstreet1": "Primaerweg 9",
         "customerprimstreet2": "Haus B", "customerprimstreet3": None}
    ie.apply_customer_address(h)
    assert (h["customerstreetname"], h["customeradditionalstreetname"]) == ("Kundenweg 2", None)


def test_rechnungsadresse_fehlt_ganz_nimmt_primaer():
    h = {"customeradrid": None, "customeradrstreet1": None, "customeradrstreet2": None,
         "customeradrstreet3": None, "customerprimstreet1": "Primaerweg 9",
         "customerprimstreet2": "Haus B", "customerprimstreet3": None,
         "customerstreetname": "Primaerweg 9"}
    ie.apply_customer_address(h)
    assert (h["customerstreetname"], h["customeradditionalstreetname"]) == ("Primaerweg 9", "Haus B")


def test_header_sql_liefert_adress_id():
    from pathlib import Path
    sql = (Path(__file__).resolve().parent.parent / "sql" / "invoice_header.sql").read_text(encoding="utf-8")
    assert "CustomerAdrId" in sql


def test_strassen_override_leert_abgeleitete_zeilen(tmp_path):
    from slim.core_slim import overrides
    overrides.save(tmp_path, 5, {"customerstreetname": "Hauptstr. 1"})
    inv = {"header": {"customerstreetname": "c/o Einkauf",
                      "customeradditionalstreetname": "Hauptstr. 1",
                      "customeraddressline": "Etage 3"}}
    out = overrides.apply_to_invoice(tmp_path, 5, inv)
    assert out["header"]["customerstreetname"] == "Hauptstr. 1"
    assert not out["header"].get("customeradditionalstreetname")
    assert not out["header"].get("customeraddressline")


def test_zusatzzeilen_sind_ueberschreibbar(tmp_path):
    from slim.core_slim import overrides
    overrides.save(tmp_path, 6, {"customerstreetname": "Hauptstr. 1",
                                 "customeradditionalstreetname": "Haus B"})
    out = overrides.apply_to_invoice(tmp_path, 6, {"header": {"customeraddressline": "x"}})
    assert out["header"]["customeradditionalstreetname"] == "Haus B"
    assert not out["header"].get("customeraddressline")


def test_validator_meldung_nennt_alle_strassenzeilen():
    from modules.invoice_validator import REQUIRED_HEADER_FIELDS
    msg = REQUIRED_HEADER_FIELDS["customerstreetname"][1]
    assert "STREET1" in msg and "STREET3" in msg


def test_fetch_invoice_verteilt_strassenzeilen(monkeypatch):
    """Echte Integration: fetch_invoice mit Fake-Cursor, nicht nur Quelltextsuche."""
    from contextlib import contextmanager
    from modules import invoice_fetcher

    rows = {
        "invoice_header.sql": ({"ID": "1", "CUSTOMERSTREETNAME": None, "CUSTOMERADRID": 7,
                                "CUSTOMERADRSTREET1": None, "CUSTOMERADRSTREET2": "Am Markt 5",
                                "CUSTOMERADRSTREET3": "c/o Einkauf",
                                "CUSTOMERPRIMSTREET1": None, "CUSTOMERPRIMSTREET2": None,
                                "CUSTOMERPRIMSTREET3": None, "DOCUMENTCURRENCYCODE": "EUR"},),
        "invoice_lines.sql": (), "invoice_tax.sql": (), "invoice_totals.sql": (),
    }

    class _Cur:
        def execute(self, sql, params=None):
            self.rows = next((r for k, r in rows.items() if sql == k), ())
            self.description = [(c,) for c in (self.rows[0].keys() if self.rows else ())]

        def fetchall(self):
            return [tuple(r.values()) for r in self.rows]

        def fetchone(self):
            return None

    class _Conn:
        def cursor(self):
            return _Cur()

    @contextmanager
    def _fake_conn():
        yield _Conn()

    monkeypatch.setattr(invoice_fetcher, "get_connection", _fake_conn)
    monkeypatch.setattr(invoice_fetcher, "_read_sql", lambda name: name)
    monkeypatch.setattr(invoice_fetcher, "_resolve_billing_reference_from_payment", lambda c, h: None)
    inv = invoice_fetcher.fetch_invoice(1)
    h = inv["header"]
    assert (h["customerstreetname"], h["customeradditionalstreetname"]) == ("Am Markt 5", "c/o Einkauf")


# --- Nutzervorgabe: Adressen niemals splitten (eine XADR-Zeile fuer alles) ---

def _both(adr, prim):
    """adr/prim = (street1, street2, street3, city, zip, country)"""
    h = {"customeradrid": 7 if adr else None}
    for prefix, vals in (("customeradr", adr), ("customerprim", prim)):
        vals = vals or (None,) * 6
        for i in range(3):
            h[f"{prefix}street{i + 1}"] = vals[i]
        h[f"{prefix}city"], h[f"{prefix}zip"], h[f"{prefix}country"] = vals[3:]
    # Werte wie bisher aus dem nvl()-SQL (gemischt) - muessen ueberschrieben werden
    h.update(customerstreetname="X", customercityname="X", customerpostalzone="X",
             customeridentificationcode="X")
    return h


def _addr(h):
    return (h["customerstreetname"], h["customercityname"], h["customerpostalzone"],
            h["customeridentificationcode"])


def test_rechnungsadresse_mit_strasse_komplett():
    h = _both(("Kundenweg 2", None, None, "Berlin", "10115", "DE"),
              ("Primaerweg 9", None, None, "Muenchen", "80331", "DE"))
    ie.apply_customer_address(h)
    assert _addr(h) == ("Kundenweg 2", "Berlin", "10115", "DE")


def test_rechnungsadresse_ohne_strasse_primaeradresse_komplett():
    h = _both((None, None, None, "Berlin", "10115", "DE"),
              ("Primaerweg 9", "Haus B", None, "Muenchen", "80331", "AT"))
    ie.apply_customer_address(h)
    assert _addr(h) == ("Primaerweg 9", "Muenchen", "80331", "AT")
    assert h["customeradditionalstreetname"] == "Haus B"


def test_keine_adresse_mit_strasse_bleibt_rechnungsadresse_ohne_mix():
    h = _both((None, None, None, "Berlin", "10115", "DE"),
              (None, None, None, "Muenchen", "80331", "DE"))
    ie.apply_customer_address(h)
    assert _addr(h) == (None, "Berlin", "10115", "DE")


def test_ohne_rechnungsadresse_primaeradresse_komplett():
    h = _both(None, ("Primaerweg 9", None, None, "Muenchen", "80331", "DE"))
    ie.apply_customer_address(h)
    assert _addr(h) == ("Primaerweg 9", "Muenchen", "80331", "DE")


def test_header_sql_liefert_ort_plz_land_je_adresse():
    from pathlib import Path
    sql = (Path(__file__).resolve().parent.parent / "sql" / "invoice_header.sql").read_text(encoding="utf-8")
    for col in ("CustomerAdrCity", "CustomerAdrZip", "CustomerAdrCountry",
                "CustomerPrimCity", "CustomerPrimZip", "CustomerPrimCountry"):
        assert col in sql
