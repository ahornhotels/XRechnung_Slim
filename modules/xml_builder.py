"""
modules/xml_builder.py
----------------------
Rendert XRechnung-XML aus Rohdaten via Jinja2.
Validiert gegen UBL-XSD (wenn vorhanden) - KoSIT-Validierung erfolgt in separater Modul-Datei.
"""
from pathlib import Path
from decimal import Decimal, InvalidOperation
from jinja2 import Environment, FileSystemLoader, select_autoescape
from lxml import etree

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
VALIDATION_DIR = Path(__file__).resolve().parent.parent / "validation"


_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _fmt(value) -> str:
    """Formatiert Number/Decimal/String mit Punkt und 2 Nachkommastellen."""
    if value is None:
        return "0.00"
    try:
        return f"{Decimal(str(value)):.2f}"
    except (InvalidOperation, ValueError):
        return "0.00"


_env.filters["fmt"] = _fmt


class XmlBuildError(Exception):
    pass


def _split_negative_lines_to_allowances(invoice: dict) -> dict:
    """Vorverarbeitung fuer XRechnung-Konformitaet (BR-27, BR-S-01).

    Suite8 liefert Pfand-Rueckgaben / Storno-Verrechnungen als negative
    Invoice-Lines mit negativem PriceAmount. XRechnung-Spec verbietet das
    (BR-27 — Item net price darf nicht negativ sein). Korrekte Abbildung:
    negative Lines werden zu dokumentebenen ``<cac:AllowanceCharge>``-
    Bloecken (mit ``<cbc:ChargeIndicator>false</cbc:ChargeIndicator>`` =
    Allowance), und das Tax-Breakdown wird neu aggregiert so dass jede
    Kategorie/Prozent-Kombi (positive Lines − Allowances) sauber abbildet.

    Zusaetzlich behebt das BR-S-01: ohne diesen Schritt klassifizierte
    Suite8 das Breakdown bei aufhebenden +/− Zeilen als ``Z`` (Zero), die
    Lines aber als ``S`` (Standard) — KoSIT lehnt den Mismatch ab. Nach
    Re-Aggregation gewinnt die Kategorie aus den Lines.

    Gibt ein NEUES Invoice-Dict zurueck (Original bleibt unangetastet).
    """
    lines     = invoice.get("lines")     or []
    breakdown = invoice.get("tax_breakdown") or []
    if not lines:
        return invoice

    # BR-Z-08 (Vorab): Z-Kategorie verlangt zwingend Percent = 0. Suite8
    # liefert manchmal die ZTCD-Originalrate (z.B. 19/7) auch bei Z (Zero rated)
    # zurueck — sowohl auf Line-Ebene als auch in der TaxBreakdown-Aggregation
    # (z.B. "MwSt7" intern mit Z geflaggt aber Percent=7).
    def _norm_z_pct(d: dict, perc_key: str, cat_key: str) -> None:
        if (str(d.get(cat_key) or "")).upper() == "Z":
            d[perc_key] = 0
    # Kopien der Lines anlegen, BEVOR _norm_z_pct in-place mutiert — sonst
    # waere der Caller-seitige Original-Invoice-Dict beschaedigt (z.B. fuer
    # JSON-Snapshot fuers Archiv oder Retry-Loops).
    normalized_lines = []
    for ln in lines:
        ln = dict(ln)
        _norm_z_pct(ln, "classifiedtaxcategorypercent", "classifiedtaxcategoryid")
        normalized_lines.append(ln)
    lines = normalized_lines
    # Breakdown ebenfalls Z-normalisieren UND leere 0/0-Zeilen herausfiltern
    # (Suite8 schreibt manchmal die volle ZTCD-Tabelle, auch wenn die Rechnung
    # die Kategorie gar nicht enthaelt — KoSIT lehnt 0/0-Zeilen mit BR-CO-17 ab).
    cleaned_breakdown = []
    for b in breakdown:
        b = dict(b)  # Kopie VOR _norm_z_pct, damit das Original-Dict unangetastet bleibt.
        cat_was = (str(b.get("taxcategoryid") or "")).upper()
        _norm_z_pct(b, "taxcategorypercent", "taxcategoryid")
        try:
            ta = Decimal(str(b.get("taxableamount") or 0))
            tx = Decimal(str(b.get("taxamount")     or 0))
            pct = Decimal(str(b.get("taxcategorypercent") or 0))
        except (InvalidOperation, ValueError):
            ta, tx, pct = Decimal(0), Decimal(0), Decimal(0)
        if ta == 0 and tx == 0:
            continue
        # BR-CO-14 + BR-Z-08: Wenn wir Z-Kategorie auf percent=0 normalisiert
        # haben, MUSS der TaxAmount jetzt 0 sein. Bei S/E-Kategorien lassen
        # wir den Suite8-Original-TaxAmount stehen — er ist gegen Brutto
        # gerundet (Suite8-Konvention) und KoSIT toleriert dort 1-Cent-Diff.
        if cat_was == "Z" and tx != 0:
            b["taxamount"] = "0.00"
        cleaned_breakdown.append(b)
    breakdown = cleaned_breakdown

    pos_lines   = []
    allowances  = []
    for ln in lines:
        try:
            price = Decimal(str(ln.get("priceamount") or ln.get("lineextensionamount") or 0))
            net   = Decimal(str(ln.get("lineextensionamountnet") or ln.get("lineextensionamount") or 0))
        except (InvalidOperation, ValueError):
            price, net = Decimal("0"), Decimal("0")
        if price < 0 or net < 0:
            allowances.append({
                "amount":     str(abs(net)),
                "category":   ln.get("classifiedtaxcategoryid") or "S",
                "percent":    ln.get("classifiedtaxcategorypercent") or 0,
                "reason":     (ln.get("itemname") or "Gutschrift"),
            })
        else:
            pos_lines.append(ln)

    # Z-Percent auf den frisch erstellten Allowances ebenfalls normalisieren.
    for al in allowances:
        _norm_z_pct(al, "percent", "category")

    if not allowances:
        # Keine negativen Zeilen → kein AllowanceCharge-Mapping noetig.
        # Aber wir geben die (Z-normalisierten) Lines + das gesaeuberte
        # Breakdown zurueck, damit BR-Z-08 und BR-CO-17 auch ohne Split
        # behoben sind.
        out = dict(invoice)
        out["lines"] = lines
        out["tax_breakdown"] = breakdown
        return out

    # Tax-Breakdown re-aggregieren: pro (category-id, percent) summieren
    # Pos-Lines Netto + Pos-Lines VAT vs. Allowances (subtrahieren).
    agg: dict = {}  # (catid, percent) -> {"taxable": Decimal, "tax": Decimal}
    for ln in pos_lines:
        cat  = ln.get("classifiedtaxcategoryid") or "S"
        pct  = Decimal(str(ln.get("classifiedtaxcategorypercent") or 0))
        net  = Decimal(str(ln.get("lineextensionamountnet") or 0))
        # VAT pro Zeile: net * pct / 100  (Net-Basis-Aggregation)
        vat  = (net * pct / Decimal(100)).quantize(Decimal("0.01"))
        key  = (cat, str(pct))
        a    = agg.setdefault(key, {"taxable": Decimal(0), "tax": Decimal(0)})
        a["taxable"] += net
        a["tax"]     += vat
    for al in allowances:
        cat  = al["category"]
        pct  = Decimal(str(al["percent"]))
        net  = Decimal(str(al["amount"]))
        vat  = (net * pct / Decimal(100)).quantize(Decimal("0.01"))
        key  = (cat, str(pct))
        a    = agg.setdefault(key, {"taxable": Decimal(0), "tax": Decimal(0)})
        a["taxable"] -= net
        a["tax"]     -= vat

    new_breakdown = [
        {
            "taxcategoryid":      cat,
            "taxcategorypercent": pct,
            "taxableamount":      str(v["taxable"]),
            "taxamount":          str(v["tax"]),
        }
        for (cat, pct), v in agg.items()
        if v["taxable"] != 0 or v["tax"] != 0
    ]

    # Falls die Re-Aggregation nichts uebrig laesst (Net = 0 nach Verrechnung),
    # fallback auf das original-breakdown — der validator wirft die Rechnung
    # dann sowieso vorher per validate_invoice ab (Net = 0).
    if not new_breakdown:
        new_breakdown = breakdown

    # LegalMonetaryTotal komplett neu rechnen, damit BR-CO-10/11/15 stimmen:
    #   BT-106 (LineExtensionAmount)    = Sum of positive lines (net)
    #   BT-107 (AllowanceTotalAmount)   = Sum of allowance amounts
    #   BT-109 (TaxExclusiveAmount)     = BT-106 - BT-107
    #   BT-110 (TaxAmount, aussen)      = Sum of breakdown.taxamount
    #   BT-112 (TaxInclusiveAmount)     = BT-109 + BT-110
    # start=Decimal(0) ist Pflicht: bei Storno-Only-Rechnungen kann pos_lines
    # leer sein, dann liefert sum([]) ein int(0) und .quantize() crasht mit
    # AttributeError. Gleiches Argument fuer allowances / new_breakdown.
    sum_lines_net = sum(
        (Decimal(str(ln.get("lineextensionamountnet") or 0)) for ln in pos_lines),
        start=Decimal(0),
    ).quantize(Decimal("0.01"))
    sum_allowances = sum(
        (Decimal(str(al["amount"])) for al in allowances),
        start=Decimal(0),
    ).quantize(Decimal("0.01"))
    new_total_vat = sum(
        (Decimal(str(r["taxamount"])) for r in new_breakdown),
        start=Decimal(0),
    ).quantize(Decimal("0.01"))
    tax_excl = (sum_lines_net - sum_allowances).quantize(Decimal("0.01"))
    tax_incl = (tax_excl + new_total_vat).quantize(Decimal("0.01"))

    out = dict(invoice)
    out["lines"]         = pos_lines
    out["allowances"]    = allowances
    out["tax_breakdown"] = new_breakdown
    out["totals"]        = dict(invoice.get("totals") or {})
    out["totals"]["invoicenet"]            = str(sum_lines_net)
    out["totals"]["allowancetotalamount"]  = str(sum_allowances)
    out["totals"]["taxexclusiveamount"]    = str(tax_excl)
    out["totals"]["invoicetaxtotal"]       = str(new_total_vat)
    out["totals"]["invoicegross"]          = str(tax_incl)

    # BR-CO-16: PayableAmount = TaxInclusiveAmount - PrepaidAmount.
    # Nach Brutto-Recompute passt das Suite8-Original-prepaid/payable nicht
    # mehr exakt zum neuen Brutto.
    # Vorgehen: Suite8-PrepaidAmount erhalten (bis maximal neuesBrutto),
    # PayableAmount = neuesBrutto - PrepaidAmount.
    # Bei vorausbezahlten Hotel-Rechnungen (Standardfall: Gast hat beim
    # Check-out alles gezahlt) bleibt damit PayableAmount = 0 — kein
    # DueDate-Problem (BR-CO-25 verlangt DueDate/PaymentTerms NUR wenn
    # Payable > 0).
    header_in = invoice.get("header") or {}
    try:
        prepaid_old = Decimal(str(header_in.get("prepaidamount") or 0))
    except (InvalidOperation, ValueError):
        prepaid_old = Decimal(0)
    prepaid_capped = min(prepaid_old, tax_incl).quantize(Decimal("0.01"))
    payable_new    = (tax_incl - prepaid_capped).quantize(Decimal("0.01"))
    out["header"] = dict(header_in)
    out["header"]["prepaidamount"] = str(prepaid_capped)
    out["header"]["payableamount"] = str(payable_new)
    return out


def _ensure_duedate(invoice: dict, is_credit_note: bool = False) -> dict:
    """BR-CO-25: PayableAmount > 0 verlangt DueDate (BT-9) oder PaymentTerms
    (BT-20). Suite8-Header liefert ``duedate`` nicht immer mit. Fallback:
    duedate = issuedate + 14 Tage (uebliche Hotel-Zahlungs-Frist). Wenn
    auch issuedate fehlt, lassen wir das Feld leer — der Pflichtfeld-
    Validator schiesst die Rechnung dann ohnehin schon weg.

    Bei CreditNotes wird KEIN duedate gesetzt: das UBL-CreditNote-Schema
    kennt cbc:DueDate nicht (waere cvc-complex-type.2.4.a). ``is_credit_note``
    muss vom Aufrufer kommen, da hier bereits abs()'d wurde und eine reine
    Sum<0-Erkennung nicht mehr greift.
    """
    from datetime import date, timedelta
    if is_credit_note:
        return invoice
    header = invoice.get("header") or {}
    try:
        payable = float(header.get("payableamount") or 0)
    except (TypeError, ValueError):
        payable = 0.0
    if payable <= 0 or header.get("duedate"):
        return invoice
    issuedate = header.get("issuedate")
    if not issuedate:
        return invoice
    try:
        # issuedate ist meistens 'YYYY-MM-DD'
        d = date.fromisoformat(str(issuedate)[:10])
    except ValueError:
        return invoice
    out = dict(invoice)
    out["header"] = dict(header)
    out["header"]["duedate"] = (d + timedelta(days=14)).isoformat()
    return out


def _normalize_tax_categories(lines: list, breakdown: list) -> tuple[list, list]:
    """Z-Kategorie-Normalisierung + 0/0-Breakdown-Filter (BR-Z-08, BR-CO-17).

    Suite8 liefert bei Z-Kategorie manchmal Percent != 0 mit. UBL verlangt
    Percent=0. Plus: Suite8 schreibt manchmal volle ZTCD-Tabelle mit leeren
    0/0-Zeilen, die KoSIT mit BR-CO-17 ablehnt.

    Gibt KOPIEN beider Listen zurueck — Original-Items unangetastet.
    """
    def _norm_z_pct(d: dict, perc_key: str, cat_key: str) -> None:
        if (str(d.get(cat_key) or "")).upper() == "Z":
            d[perc_key] = 0

    normalized_lines = []
    for ln in lines or []:
        ln = dict(ln)
        _norm_z_pct(ln, "classifiedtaxcategorypercent", "classifiedtaxcategoryid")
        normalized_lines.append(ln)

    cleaned_breakdown = []
    for b in breakdown or []:
        b = dict(b)
        cat_was = (str(b.get("taxcategoryid") or "")).upper()
        _norm_z_pct(b, "taxcategorypercent", "taxcategoryid")
        try:
            ta = Decimal(str(b.get("taxableamount") or 0))
            tx = Decimal(str(b.get("taxamount") or 0))
        except (InvalidOperation, ValueError):
            ta, tx = Decimal(0), Decimal(0)
        if ta == 0 and tx == 0:
            continue
        if cat_was == "Z" and tx != 0:
            b["taxamount"] = "0.00"
        cleaned_breakdown.append(b)

    return normalized_lines, cleaned_breakdown


def _make_positive_for_credit_note(invoice: dict) -> dict:
    """UBL CreditNote verlangt POSITIVE Werte im Body. Suite8 liefert sie
    bei Gutschriften aber negativ (Sum<0). Diese Funktion wandelt alle
    Line-Werte, Tax-Breakdown-Werte, Totals UND header.payableamount /
    header.prepaidamount in positive Betraege um. Plus Z-Normalisierung
    und 0/0-Breakdown-Filter (BR-Z-08, BR-CO-17).

    Wird nur fuer CreditNotes aufgerufen, NICHT fuer regulaere Invoices.
    Gibt ein NEUES Dict zurueck (Original unangetastet).
    """
    # Z-Normalisierung + 0/0-Filter zuerst (KoSIT BR-Z-08 / BR-CO-17)
    norm_lines, norm_breakdown = _normalize_tax_categories(
        invoice.get("lines") or [],
        invoice.get("tax_breakdown") or [],
    )

    out = dict(invoice)

    # Header kopieren UND payable/prepaid abs()'d (BR-CO-16-Konsistenz)
    out["header"] = dict(invoice.get("header") or {})
    for key in ("payableamount", "prepaidamount"):
        v = out["header"].get(key)
        if v is None or v == "":
            continue
        try:
            out["header"][key] = str(abs(Decimal(str(v))))
        except (InvalidOperation, ValueError):
            pass

    # Lines: alle Betragsfelder abs()'d
    out["lines"] = []
    for ln in norm_lines:
        for key in ("priceamount", "lineextensionamount", "lineextensionamountnet"):
            v = ln.get(key)
            if v is None:
                continue
            try:
                ln[key] = str(abs(Decimal(str(v))))
            except (InvalidOperation, ValueError):
                pass
        out["lines"].append(ln)

    # Breakdown: taxableamount + taxamount abs()'d
    out["tax_breakdown"] = []
    for b in norm_breakdown:
        for key in ("taxableamount", "taxamount"):
            v = b.get(key)
            if v is None:
                continue
            try:
                b[key] = str(abs(Decimal(str(v))))
            except (InvalidOperation, ValueError):
                pass
        out["tax_breakdown"].append(b)

    # Totals abs()'d (inkl. spay_cl, taxexcl, allowancetotal)
    out["totals"] = dict(invoice.get("totals") or {})
    for key in ("invoicenet", "invoicegross", "invoicetaxtotal", "spay_cl",
                "taxexclusiveamount", "allowancetotalamount"):
        v = out["totals"].get(key)
        if v is None:
            continue
        try:
            out["totals"][key] = abs(float(v))
        except (TypeError, ValueError):
            pass
    return out


def render(invoice: dict, version: str = "3.0") -> bytes:
    """Rendert Invoice-Dict zu XML-Bytes (UTF-8). Waehlt automatisch
    zwischen Invoice- und CreditNote-Template basierend auf is_credit_note().

    Pre-Processing:
    - CreditNote: _make_positive_for_credit_note (alle Betraege positiv)
    - Invoice:    _split_negative_lines_to_allowances (BR-27/BR-S-01-Fixes)
    Beide bekommen anschliessend _ensure_duedate (BR-CO-25).
    """
    from modules.invoice_fetcher import is_credit_note
    is_cn = is_credit_note(invoice)
    if is_cn:
        prepared = _make_positive_for_credit_note(invoice)
        tmpl_name = f"creditnote_{version}.xml.j2"
    else:
        prepared = _split_negative_lines_to_allowances(invoice)
        tmpl_name = f"xrechnung_{version}.xml.j2"
    prepared = _ensure_duedate(prepared, is_credit_note=is_cn)
    template = _env.get_template(tmpl_name)
    return template.render(**prepared).encode("utf-8")


def validate_xsd(xml_bytes: bytes, version: str = "3.0.2", credit_note: bool = False) -> None:
    """Validiert XML gegen UBL-2.1-Schema falls vorhanden. Sonst No-Op + Warnung im Log.
    Wirft XmlBuildError bei Schema-Fehler.

    credit_note=True wechselt zum UBL-CreditNote-XSD.
    """
    sub = "UBL-CreditNote-2.1.xsd" if credit_note else "UBL-Invoice-2.1.xsd"
    xsd_path = VALIDATION_DIR / f"xrechnung-{version}" / "ubl-2.1" / "maindoc" / sub
    if not xsd_path.exists():
        # Schema noch nicht installiert - silent skip
        return
    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    try:
        doc = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        raise XmlBuildError(f"XML-Syntax-Fehler: {e}")
    if not schema.validate(doc):
        errors = [str(e) for e in schema.error_log]
        raise XmlBuildError("XML-Schema-Validierung fehlgeschlagen:\n" + "\n".join(errors))


def build_and_validate(invoice: dict, version: str = "3.0", xsd_version: str = "3.0.2") -> bytes:
    """Convenience: rendert + validiert (XSD only)."""
    from modules.invoice_fetcher import is_credit_note
    xml = render(invoice, version)
    validate_xsd(xml, version=xsd_version, credit_note=is_credit_note(invoice))
    return xml
