"""Guard-Tests fuer die uebernommenen SQL-Fixes vom 2026-07-03 (FW).

Quellen: docs/invoice_header_20260703.txt, docs/invoice_tax_20260703.txt,
docs/invoice_totals_20260703.txt. Die Tests sichern die Marker der Fixes,
damit ein Refresh der Templates sie nicht stillschweigend zuruecksetzt.
"""
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def _read(name):
    return (SQL_DIR / name).read_text(encoding="utf-8")


def test_header_hat_adress_fallback_auf_primaeradresse():
    """Kundenadresse faellt auf die Primaeradresse (xadr_primary=1) zurueck,
    wenn die Rechnung ohne Adresse angelegt wurde."""
    sql = _read("invoice_header.sql")
    assert sql.lower().count("xadr_primary=1") >= 4  # Strasse/Ort/PLZ/Land
    assert "CustomerStreetName" in sql
    # PaymentRefComment (BG-3-Fallback) muss den Merge ueberlebt haben
    assert "PaymentRefComment" in sql


def test_tax_taxamount_aus_zeilen_mwst_summiert():
    """TaxAmount je Steuersatz kommt aus den gerundeten Zeilen-MwSt-Betraegen
    (0,5-Cent-Steuerueberschuss-Fix), nicht mehr aus TAX_AMOUNT_S."""
    sql = _read("invoice_tax.sql")
    assert "TBH_LR_DE_PEPPOL_XML_SINGLE" in sql
    assert "LineExtensionAmountVat from TBH_LR_DE_PEPPOL_XML_SINGLE" in sql


def test_tax_taxamount_korreliert_ueber_ztcd_nicht_prozentsatz():
    """Finding 1 (BR-CO-14): Der TaxAmount-Subselect muss die Zeilen-CTE ueber
    die Steuercode-ID (ztcd_id) korrelieren, nicht ueber den Prozentsatz —
    sonst bekommen zwei Steuercodes mit gleichem Satz beide die volle
    Gruppen-VAT (Doppelzaehlung). Plus NVL-Fallback statt stillem 0.00."""
    sql = _read("invoice_tax.sql")
    flat = sql.replace(" ", "").replace("\n", "")
    # CTE traegt die ztcd_id und gruppiert danach
    assert "ClassifiedTaxCategoryZtcdId" in sql
    assert "groupbyZINV_ID,ClassifiedTaxCategoryPercent,ClassifiedTaxCategoryZtcdId".replace(" ", "") in flat \
        or "ClassifiedTaxCategoryZtcdId" in flat.split("groupby")[-1]
    # TaxAmount-Subselect korreliert ueber ztcd_id, nicht ueber evaluatemath-Percent
    assert "ClassifiedTaxCategoryZtcdId=ztcd.ztcd_id" in flat
    # Randfall ohne CTE-Treffer faellt auf den posting-basierten Wert zurueck
    assert "NVL((selectLineExtensionAmountVatfromTBH_LR_DE_PEPPOL_XML_SINGLE" in flat


def test_zeilenlogik_synchron_ueber_drei_sql():
    """Finding 11: Die Zeilen-Berechnungslogik ist (noch) dreifach kopiert
    (invoice_lines.sql + CTEs in invoice_tax.sql/invoice_totals.sql). Bis zu
    einer echten Konsolidierung sichert dieser Guard, dass eine Aenderung nicht
    in nur einer Kopie landet — stille Divergenz fuehrt zu Netto+Steuer<>Brutto
    (BR-CO-*), genau der Fehlerklasse, die der 03.07.-Fix beseitigt hat."""
    fragments = (
        "round(z.zpos_grossunitprice*z.zpos_quantity,2)",
        ("(select evaluatemath(replace((replace(ztcd_udf,'x',100)),';',',')) "
         "from zpos Z2,ztcd where Z2.zpos_taxlink_id=z.zpos_taxlink_id and "
         "Z2.zpos_cdt=2 and Z2.zpos_ztcd_id=ztcd.ztcd_id)"),
    )
    sqls = {name: _read(f"invoice_{name}.sql").replace(" ", "").replace("\n", "")
            for name in ("lines", "tax", "totals")}
    for frag in fragments:
        norm = frag.replace(" ", "").replace("\n", "")
        for name, sql in sqls.items():
            assert norm in sql, f"invoice_{name}.sql: Zeilenlogik divergiert bei {frag[:40]!r}"


def test_totals_netto_und_steuer_aus_zeilenlogik():
    """InvoiceNet/InvoiceTaxTotal kommen aus derselben Zeilen-Logik wie
    invoice_lines.sql (Netto+Steuer=Brutto-Fix)."""
    sql = _read("invoice_totals.sql")
    assert "TBH_LR_DE_PEPPOL_XML_SINGLE" in sql
    assert "sum(LineExtensionAmountNet_number)" in sql
    assert "sum(LineExtensionAmountVat_number)" in sql
