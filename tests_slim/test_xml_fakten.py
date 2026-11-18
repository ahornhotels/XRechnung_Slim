"""Tests: Kerndaten aus einer archivierten XRechnung lesen (fuer das Archiv)."""
from slim.core_slim import xml_fakten

NS = ('xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
      'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"')

RECHNUNG = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" {NS}>
  <cbc:ID>900001</cbc:ID>
  <cbc:IssueDate>2026-11-14</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyName><cbc:Name>Kurzname</cbc:Name></cac:PartyName>
    <cac:PartyLegalEntity><cbc:RegistrationName>Muster GmbH</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="EUR">1234.56</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>""".encode("utf-8")

GUTSCHRIFT = f"""<?xml version="1.0" encoding="UTF-8"?>
<CreditNote xmlns="urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2" {NS}>
  <cbc:ID>900002</cbc:ID>
  <cbc:IssueDate>2026-11-15</cbc:IssueDate>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyName><cbc:Name>Nur Name</cbc:Name></cac:PartyName>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="EUR">89.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</CreditNote>""".encode("utf-8")


def test_fakten_rechnung():
    f = xml_fakten.lies(RECHNUNG)
    assert f == {"rechnung": "900001", "rechnungsdatum": "2026-11-14", "art": "Rechnung",
                 "betrag": "1234.56", "waehrung": "EUR", "kaeufer": "Muster GmbH"}


def test_fakten_gutschrift():
    f = xml_fakten.lies(GUTSCHRIFT)
    assert f["art"] == "Gutschrift" and f["rechnung"] == "900002"
    assert f["kaeufer"] == "Nur Name" and f["waehrung"] == "EUR"


def test_fakten_kaputte_xml():
    assert xml_fakten.lies(b"<x") == {}


def test_fakten_fremdes_dokument():
    assert xml_fakten.lies(b"<Invoice>OK</Invoice>") == {}


def test_doctype_wird_abgelehnt():
    boese = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
             b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">&a;</Invoice>')
    assert xml_fakten.lies(boese) == {}
    assert xml_fakten.parse(boese) == (None, None)
