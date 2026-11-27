"""Tests: lesbare Rechnungsansicht aus einer archivierten XRechnung."""
from slim.core_slim import xml_ansicht

_NS = ('xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
       'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"')


def _doc(root, line_tag, qty_tag):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<{root} xmlns="urn:oasis:names:specification:ubl:schema:xsd:{root}-2" {_NS}>
  <cbc:ID>900001</cbc:ID>
  <cbc:IssueDate>2026-11-14</cbc:IssueDate>
  <cbc:DueDate>2026-11-28</cbc:DueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:Note>Gast: Erika Muster, Zimmer 101</cbc:Note>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cbc:BuyerReference>PO-1</cbc:BuyerReference>
  <cac:InvoicePeriod><cbc:StartDate>2026-11-12</cbc:StartDate><cbc:EndDate>2026-11-14</cbc:EndDate></cac:InvoicePeriod>
  <cac:OrderReference><cbc:ID>V-77</cbc:ID></cac:OrderReference>
  <cac:BillingReference><cac:InvoiceDocumentReference><cbc:ID>800001</cbc:ID><cbc:IssueDate>2026-10-01</cbc:IssueDate></cac:InvoiceDocumentReference></cac:BillingReference>
  <cac:AccountingSupplierParty><cac:Party>
    <cbc:EndpointID schemeID="EM">buchhaltung@hotel.example</cbc:EndpointID>
    <cac:PostalAddress><cbc:StreetName>Hauptstr. 1</cbc:StreetName><cbc:CityName>Musterstadt</cbc:CityName>
      <cbc:PostalZone>12345</cbc:PostalZone></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>DE123456789</cbc:CompanyID></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Hotel Beispiel GmbH</cbc:RegistrationName></cac:PartyLegalEntity>
    <cac:Contact><cbc:Name>Buchhaltung</cbc:Name><cbc:Telephone>01234 5678</cbc:Telephone><cbc:ElectronicMail>buchhaltung@hotel.example</cbc:ElectronicMail></cac:Contact>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cbc:EndpointID schemeID="EM">kunde@firma.example</cbc:EndpointID>
    <cac:PostalAddress><cbc:StreetName>Am Markt 5</cbc:StreetName><cbc:AdditionalStreetName>Abt. Einkauf</cbc:AdditionalStreetName><cbc:CityName>Beispielort</cbc:CityName>
      <cbc:PostalZone>54321</cbc:PostalZone><cac:AddressLine><cbc:Line>Postfach 9</cbc:Line></cac:AddressLine><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyLegalEntity><cbc:RegistrationName>Muster GmbH</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:Delivery><cac:DeliveryParty><cac:PartyName><cbc:Name>Erika Muster</cbc:Name></cac:PartyName></cac:DeliveryParty></cac:Delivery>
  <cac:PaymentMeans><cbc:PaymentMeansCode>30</cbc:PaymentMeansCode><cac:PayeeFinancialAccount><cbc:ID>DE00123</cbc:ID><cbc:Name>Hotel Beispiel GmbH</cbc:Name><cac:FinancialInstitutionBranch><cbc:ID>BICBIC</cbc:ID></cac:FinancialInstitutionBranch></cac:PayeeFinancialAccount></cac:PaymentMeans>
  <cac:PaymentTerms><cbc:Note>Zahlbar in 14 Tagen</cbc:Note></cac:PaymentTerms>
  <cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator><cbc:AllowanceChargeReason>Abzüglich Anzahlungsrechnung Nr. 800001</cbc:AllowanceChargeReason><cbc:Amount currencyID="EUR">10.00</cbc:Amount><cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>7</cbc:Percent></cac:TaxCategory></cac:AllowanceCharge>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">7.00</cbc:TaxAmount>
    <cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">100.00</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="EUR">7.00</cbc:TaxAmount>
      <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>7</cbc:Percent></cac:TaxCategory></cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">107.00</cbc:TaxInclusiveAmount>
    <cbc:AllowanceTotalAmount currencyID="EUR">10.00</cbc:AllowanceTotalAmount>
    <cbc:PrepaidAmount currencyID="EUR">7.00</cbc:PrepaidAmount>
    <cbc:PayableAmount currencyID="EUR">100.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:{line_tag}><cbc:ID>1</cbc:ID><cbc:Note>Erika Muster, Zimmer 101</cbc:Note><cbc:{qty_tag} unitCode="DAY">2</cbc:{qty_tag}>
    <cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cac:InvoicePeriod><cbc:StartDate>2026-11-12</cbc:StartDate><cbc:EndDate>2026-11-13</cbc:EndDate></cac:InvoicePeriod>
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
                                "preis": "50.00", "netto": "100.00", "steuer_prozent": "7",
                                "hinweis": "Erika Muster, Zimmer 101", "von": "2026-11-12", "bis": "2026-11-13"}]
    assert a["steuern"] == [{"kategorie": "S", "prozent": "7", "basis": "100.00", "betrag": "7.00"}]
    assert a["summen"] == {"positionen": "100.00", "abschlaege": "10.00", "zuschlaege": None,
                           "netto": "100.00", "steuer": "7.00", "brutto": "107.00",
                           "vorauszahlung": "7.00", "zahlbetrag": "100.00"}
    assert a["hinweise"] == ["Gast: Erika Muster, Zimmer 101"]


def test_ansicht_gutschrift():
    a = xml_ansicht.lies(_doc("CreditNote", "CreditNoteLine", "CreditedQuantity"))
    assert a["fakten"]["art"] == "Gutschrift"
    assert a["positionen"][0]["menge"] == "2"


def test_ansicht_keine_xrechnung():
    assert xml_ansicht.lies(b"<a/>") is None


def test_ansicht_zeigt_alle_gesendeten_angaben():
    """Die Ansicht soll dem entsprechen, was hinausging - nicht nur Kopf und Summen."""
    a = xml_ansicht.lies(_doc("Invoice", "InvoiceLine", "InvoicedQuantity"))
    assert a["kopf"] == {
        "typ": "380", "faellig": "2026-11-28", "von": "2026-11-12", "bis": "2026-11-14",
        "bestellnummer": "V-77", "bezuege": [{"nr": "800001", "datum": "2026-10-01"}],
        "leistungsempfaenger": "Erika Muster", "zahlungsbedingungen": "Zahlbar in 14 Tagen",
        "zahlung": {"code": "30", "konto": "DE00123", "inhaber": "Hotel Beispiel GmbH", "bic": "BICBIC"}}
    k, v = a["kaeufer"], a["verkaeufer"]
    assert k["email"] == "kunde@firma.example" and k["zusatz"] == "Abt. Einkauf"
    assert k["adresszeile"] == "Postfach 9" and k["land"] == "DE"
    assert v["email"] == "buchhaltung@hotel.example"
    assert v["kontakt"] == {"name": "Buchhaltung", "telefon": "01234 5678", "email": "buchhaltung@hotel.example"}
    assert a["nachlaesse"] == [{"zuschlag": False, "grund": "Abzüglich Anzahlungsrechnung Nr. 800001",
                                "betrag": "10.00", "kategorie": "S", "prozent": "7"}]


def test_ansicht_ohne_zusatzangaben_bleibt_leer():
    a = xml_ansicht.lies(b"""<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"/>""")
    assert a["kopf"]["bezuege"] == [] and a["kopf"]["zahlung"] is None and a["kopf"]["typ"] is None
    assert a["nachlaesse"] == [] and a["hinweise"] == [] and a["positionen"] == []


def test_ansicht_js_nennt_die_felder():
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "slim" / "frontend" / "ansicht.js").read_text(encoding="utf-8")
    for wort in ("Bemerkung (BT-22)", "Bestellnummer (BT-13)", "Leistungsempfänger (BT-70)",
                 "Bezug auf Rechnung", "Leistungszeitraum", "Zahlungsbedingungen", "IBAN", "p.hinweis", "a.nachlaesse"):
        assert wort in js, wort
