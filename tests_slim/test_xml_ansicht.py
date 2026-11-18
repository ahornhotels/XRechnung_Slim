"""Tests: lesbare Rechnungsansicht aus einer archivierten XRechnung."""
from slim.core_slim import xml_ansicht

_NS = ('xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
       'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"')


def _doc(root, line_tag, qty_tag):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<{root} xmlns="urn:oasis:names:specification:ubl:schema:xsd:{root}-2" {_NS}>
  <cbc:ID>900001</cbc:ID>
  <cbc:IssueDate>2026-11-14</cbc:IssueDate>
  <cbc:Note>Gast: Erika Muster, Zimmer 101</cbc:Note>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cbc:BuyerReference>PO-1</cbc:BuyerReference>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PostalAddress><cbc:StreetName>Hauptstr. 1</cbc:StreetName><cbc:CityName>Musterstadt</cbc:CityName>
      <cbc:PostalZone>12345</cbc:PostalZone></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>DE123456789</cbc:CompanyID></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Hotel Beispiel GmbH</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PostalAddress><cbc:StreetName>Am Markt 5</cbc:StreetName><cbc:CityName>Beispielort</cbc:CityName>
      <cbc:PostalZone>54321</cbc:PostalZone></cac:PostalAddress>
    <cac:PartyLegalEntity><cbc:RegistrationName>Muster GmbH</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">7.00</cbc:TaxAmount>
    <cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">100.00</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="EUR">7.00</cbc:TaxAmount>
      <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>7</cbc:Percent></cac:TaxCategory></cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">107.00</cbc:TaxInclusiveAmount>
    <cbc:PrepaidAmount currencyID="EUR">7.00</cbc:PrepaidAmount>
    <cbc:PayableAmount currencyID="EUR">100.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:{line_tag}><cbc:ID>1</cbc:ID><cbc:{qty_tag} unitCode="DAY">2</cbc:{qty_tag}>
    <cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Übernachtung</cbc:Name>
      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>7</cbc:Percent></cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">50.00</cbc:PriceAmount></cac:Price>
  </cac:{line_tag}>
</{root}>""".encode("utf-8")


def test_ansicht_rechnung():
    a = xml_ansicht.lies(_doc("Invoice", "InvoiceLine", "InvoicedQuantity"))
    assert a["fakten"]["art"] == "Rechnung" and a["fakten"]["kaeuferreferenz"] == "PO-1"
    assert a["verkaeufer"]["name"] == "Hotel Beispiel GmbH" and a["verkaeufer"]["ust_id"] == "DE123456789"
    assert a["kaeufer"]["name"] == "Muster GmbH" and a["kaeufer"]["ort"] == "54321 Beispielort"
    assert a["positionen"] == [{"nr": "1", "bezeichnung": "Übernachtung", "menge": "2", "einheit": "DAY",
                                "preis": "50.00", "netto": "100.00", "steuer_prozent": "7"}]
    assert a["steuern"] == [{"kategorie": "S", "prozent": "7", "basis": "100.00", "betrag": "7.00"}]
    assert a["summen"] == {"netto": "100.00", "steuer": "7.00", "brutto": "107.00",
                           "vorauszahlung": "7.00", "zahlbetrag": "100.00"}
    assert a["hinweise"] == ["Gast: Erika Muster, Zimmer 101"]


def test_ansicht_gutschrift():
    a = xml_ansicht.lies(_doc("CreditNote", "CreditNoteLine", "CreditedQuantity"))
    assert a["fakten"]["art"] == "Gutschrift"
    assert a["positionen"][0]["menge"] == "2"


def test_ansicht_keine_xrechnung():
    assert xml_ansicht.lies(b"<a/>") is None
