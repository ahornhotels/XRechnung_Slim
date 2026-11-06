"""
modules/invoice_fetcher.py
--------------------------
Laedt Rechnungs-Rohdaten aus Suite8 via Inline-SQL-Templates.
Joint Header/Lines/Tax/Totals zu einer einheitlichen Python-Datenstruktur.

Datenstruktur:
{
    "zinv_id": int,
    "header": {col_lowercase: value, ...},   # aus invoice_header.sql + Totals gemerged
    "lines":  [{col: val, ...}, ...],         # aus invoice_lines.sql
    "tax_breakdown": [{col: val, ...}, ...],  # aus invoice_tax.sql
    "totals": {col: val, ...},                # aus invoice_totals.sql
}
"""
import logging
import re
from pathlib import Path
from typing import Optional

from core.db_connector import get_connection
from core.config_loader import load_json, CONFIG_DIR

logger = logging.getLogger(__name__)
SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def _default_currency() -> str:
    """Liefert die Default-Waehrung aus config/hotel.json (Default 'EUR')."""
    hotel = load_json(CONFIG_DIR / "hotel.json", default={}) or {}
    return (hotel.get("currency") or "EUR").upper()


def _seller_contact_defaults() -> dict:
    """Optionale Overrides aus config/hotel.json fuer den Seller-Contact (BR-DE-5).
    Werden nur verwendet wenn WUSS-Felder leer sind.
    Felder: seller_contact_name, seller_contact_phone, seller_contact_email
    """
    hotel = load_json(CONFIG_DIR / "hotel.json", default={}) or {}
    return {
        "name":  hotel.get("seller_contact_name"),
        "phone": hotel.get("seller_contact_phone"),
        "email": hotel.get("seller_contact_email"),
    }


# Marker, die im aktuellen Repo-Template vorkommen. Fehlen sie in einem
# Operator-Override, ist der Override vor den zugehoerigen Fixes gespeichert
# worden und ueberschattet sie still — bei Aenderung der Templates pflegen.
_EXPECTED_OVERRIDE_MARKERS = {
    "invoice_header.sql": ("PaymentRefComment", "xadr_primary"),
    "invoice_tax.sql": ("ClassifiedTaxCategoryZtcdId",),
    "invoice_totals.sql": ("LineExtensionAmountVat_number",),
    "invoice_lines.sql": ("DepositZinvId",),
}
_warned_stale_overrides: set[str] = set()


def _stale_override_markers(name: str, sql_text: str) -> list[str]:
    """Erwartete Marker, die im Override-SQL fehlen (Hinweis auf einen
    veralteten Override, der neuere Repo-Fixes ueberschattet)."""
    return [m for m in _EXPECTED_OVERRIDE_MARKERS.get(name, ()) if m not in sql_text]


def _read_sql(name: str) -> str:
    """Liest ein SQL-Template. Bevorzugt einen Operator-Override unter
    ``<data_dir>/sql_overrides/<name>`` — wenn vorhanden, sonst die Repo-
    Vorlage in ``sql/``.

    Der ``data_dir`` wird relativ zu ``CONFIG_DIR`` ermittelt: das ist
    das selbe Pfad-Schema, das Slim und Big-App ohnehin nutzen
    (``slim/data`` neben ``slim/config`` bzw. ``data`` neben ``config``).
    """
    override = (CONFIG_DIR.parent / "data" / "sql_overrides" / name)
    if override.exists():
        try:
            content = override.read_text(encoding="utf-8")
            if content.strip():
                missing = _stale_override_markers(name, content)
                if missing and name not in _warned_stale_overrides:
                    _warned_stale_overrides.add(name)
                    logger.warning(
                        "SQL-Override %s wirkt veraltet — fehlende Marker: %s. Er "
                        "ueberschattet neuere Repo-Fixes; im SQL-Editor neu "
                        "speichern oder loeschen.", name, ", ".join(missing))
                return content
        except OSError:
            logger.exception("SQL-Override nicht lesbar: %s — fallback auf Repo", override)
    return (SQL_DIR / name).read_text(encoding="utf-8")


def _rows_to_dicts(cursor) -> list[dict]:
    """Konvertiert Oracle-Cursor-Resultset zu Liste von Dicts mit lowercase Keys."""
    if cursor.description is None:
        return []
    cols = [c[0].lower() for c in cursor.description]
    rows = cursor.fetchall()
    result = []
    for row in rows:
        d = {}
        for col, val in zip(cols, row):
            # Oracle LOB-Typen lesen falls noetig
            if hasattr(val, "read"):
                val = val.read()
            d[col] = val
        result.append(d)
    return result


# Aeltere Suite8-Versionen kennen ZPOS.ZPOS_DEPOSIT_ZINV_ID evtl. nicht. Dann
# laeuft die Positions-SQL ohne Anzahlungsbezug (Spalte -> NULL), statt fuer
# ALLE Rechnungen mit ORA-00904 zu scheitern. Merkt sich das pro Prozess.
_deposit_column_missing = False


def _lines_sql_without_deposit(sql: str) -> str:
    return re.sub(r"z\.zpos_deposit_zinv_id", "to_number(null)", sql, flags=re.IGNORECASE)


def _fetch_lines(cur, zinv_id: int) -> list[dict]:
    global _deposit_column_missing
    sql = _read_sql("invoice_lines.sql")
    if _deposit_column_missing:
        sql = _lines_sql_without_deposit(sql)
    try:
        cur.execute(sql, {"zinv_id": zinv_id})
    except Exception as e:
        if _deposit_column_missing or "ZPOS_DEPOSIT_ZINV_ID" not in str(e).upper():
            raise
        _deposit_column_missing = True
        logger.warning(
            "Spalte ZPOS.ZPOS_DEPOSIT_ZINV_ID fehlt in dieser Suite8-Version - "
            "Positionen ohne Anzahlungsbezug (%s)", e)
        cur.execute(_lines_sql_without_deposit(sql), {"zinv_id": zinv_id})
    return _rows_to_dicts(cur)


def is_deposit_line(line: dict) -> bool:
    """True fuer die Anzahlungsabbuchung beim Check-in: Position mit Verweis
    auf die Anzahlungsrechnung (ZPOS_DEPOSIT_ZINV_ID)."""
    try:
        return int(line.get("depositzinvid") or 0) > 0
    except (TypeError, ValueError):
        return False


def fetch_invoice(zinv_id: int) -> Optional[dict]:
    """Holt alle Daten zu einer Rechnung. Gibt None zurueck wenn Header leer (Rechnung nicht gefunden)."""
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(_read_sql("invoice_header.sql"), {"zinv_id": zinv_id})
        header_rows = _rows_to_dicts(cur)
        if not header_rows:
            return None
        header = header_rows[0]

        lines = _fetch_lines(cur, zinv_id)

        cur.execute(_read_sql("invoice_tax.sql"), {"zinv_id": zinv_id})
        tax_breakdown = _rows_to_dicts(cur)

        cur.execute(_read_sql("invoice_totals.sql"), {"zinv_id": zinv_id})
        totals_rows = _rows_to_dicts(cur)
        totals = totals_rows[0] if totals_rows else {}

        # Header NULL-Felder mit Totals fuellen (per Spec sind die in HEA absichtlich NULL).
        # TBH_EEI_FOLIO_TOT liefert: invoicegross, invoicenet, invoicetaxtotal, spay_cl.
        # Mapping folgt der ORIGINAL-View TBH_LR_DE_PEPPOL_XML_FOL_HEA:
        #   PayableAmount = SPAY_CL  (vom System verbuchter Payable-Betrag)
        #   PrepaidAmount = Gross - SPAY_CL  (Rest, der als bereits beglichen gilt)
        for src, dst in [
            ("invoicenet",       "lineextensionamount"),
            ("invoicenet",       "taxexclusiveamount"),
            ("invoicegross",     "taxinclusiveamount"),
        ]:
            if totals.get(src) is not None:
                header[dst] = f"{float(totals[src]):.2f}"
        gross = totals.get("invoicegross")
        spay_cl = totals.get("spay_cl")
        if gross is not None:
            spay_cl_val = float(spay_cl) if spay_cl is not None else 0.0
            gross_val = float(gross)
            header["payableamount"] = f"{spay_cl_val:.2f}"
            header["prepaidamount"] = f"{gross_val - spay_cl_val:.2f}"

        # Waehrung: wenn Suite8 nichts liefert (WUSS.BaseCurrency nicht gepflegt),
        # nimm Default aus config/hotel.json (Default 'EUR'). XRechnung braucht
        # zwingend eine 3-stellige ISO-Waehrung.
        if not header.get("documentcurrencycode"):
            currency = _default_currency()
            header["documentcurrencycode"] = currency
            logger.debug("documentcurrencycode aus Hotel-Default gesetzt: %s", currency)

        # BR-DE-5: Seller contact point (cac:Contact mit cbc:Name) ist Pflicht.
        # WUSS-Reihenfolge: 1) UDEF_XRECHNUNG_RESPONSIBLE_NAME / Hoteltel / Hotelemail
        #                   2) hotel.json Overrides (seller_contact_*)
        #                   3) Hotel-Name als Fallback fuer Name (garantiert nicht leer)
        defaults = _seller_contact_defaults()
        if not (header.get("suppliercontactname") or "").strip():
            header["suppliercontactname"] = defaults["name"] or header.get("suppliername")
        if not (header.get("suppliercontacttelephone") or "").strip():
            header["suppliercontacttelephone"] = defaults["phone"]
        if not (header.get("suppliercontactelectronicmail") or "").strip():
            header["suppliercontactelectronicmail"] = defaults["email"]

        # CreditNote-Override: wenn die Heuristik zuschlaegt aber das SQL noch
        # '380' geliefert hat (Hotel nutzt ROLE=0 mit Sum<0), korrigiere auf '381'.
        _provisional = {
            "header": header, "lines": lines,
            "tax_breakdown": tax_breakdown, "totals": totals,
        }
        if is_credit_note(_provisional):
            header["invoicetypecode"] = "381"

        _resolve_billing_reference_from_payment(cur, header)

        return {
            "zinv_id": zinv_id,
            "header": header,
            "lines": lines,
            "tax_breakdown": tax_breakdown,
            "totals": totals,
        }


def list_recent_invoices(days: int = 7) -> list[dict]:
    """Listet Rechnungen der letzten <days> Tage."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(_read_sql("invoice_list.sql"), {"days": days})
        return _rows_to_dicts(cur)


def find_zinv_id_by_number(zinv_number: str) -> Optional[int]:
    """Suche nach Rechnungsnummer (zinv_number) in Suite8 und gib die interne
    zinv_id zurueck. Trimmt Whitespace, exact match (case-sensitive im ZINV).

    Returns None wenn nicht gefunden.
    Falls mehrere Treffer (sollte nicht passieren, ZINV_NUMBER ist eindeutig),
    wird die hoechste zinv_id (neueste) zurueckgegeben.
    """
    nr = (zinv_number or "").strip()
    if not nr:
        return None
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT MAX(zinv_id) FROM zinv WHERE zinv_number = :nr",
            {"nr": nr},
        )
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None


def _extract_number_candidates(comment) -> list[str]:
    """Alle zusammenhaengenden Ziffernfolgen aus einem Freitext, laengste zuerst
    (Tie-Break gegen Streuzahlen wie Jahreszahlen); bei gleicher Laenge bleibt
    die Originalreihenfolge erhalten."""
    if not comment or not str(comment).strip():
        return []
    return sorted(re.findall(r"\d+", str(comment)), key=len, reverse=True)


def _resolve_billing_reference_from_payment(cur, header: dict) -> None:
    """BG-3-Fallback fuer Gutschriften (InvoiceTypeCode 381) ohne
    ZINV_VOID_ZINV_ID-Bezug: In der Hotel-Praxis traegt der Operator die
    Original-Rechnungsnummer als Freitext in den Kommentar der Zahlungszeile
    ein (Header-Feld ``paymentrefcomment`` aus invoice_header.sql).

    Jeder Ziffern-Kandidat wird gegen ZINV validiert; der erste Treffer setzt
    ``billingreferenceid`` und ``billingreferenceissuedate``. Kein Treffer ->
    Feld bleibt leer, der Validator meldet weiterhin BG-3 (kein Fake-Bezug).
    """
    if (header.get("invoicetypecode") or "") != "381":
        return
    if (str(header.get("billingreferenceid") or "")).strip():
        return
    # Die eigene Rechnungsnummer der Gutschrift darf nie als (Selbst-)Bezug
    # gewinnen — sie existiert per Definition in ZINV.
    own = (str(header.get("id") or "")).strip()
    for nr in _extract_number_candidates(header.get("paymentrefcomment")):
        if nr == own:
            continue
        # Bei doppelten Nummern die neueste Rechnung (hoechste zinv_id) nehmen —
        # konsistent zu find_zinv_id_by_number.
        cur.execute(
            "SELECT zinv_number, TO_CHAR(zinv_date, 'YYYY-MM-DD') FROM zinv "
            "WHERE zinv_id = (SELECT MAX(zinv_id) FROM zinv WHERE zinv_number = :nr)",
            {"nr": nr},
        )
        row = cur.fetchone()
        if row:
            header["billingreferenceid"] = row[0]
            header["billingreferenceissuedate"] = row[1]
            logger.info(
                "BillingReference aus Zahlungs-Kommentar aufgeloest: %s", row[0])
            return


def is_void_storno(invoice: dict) -> bool:
    """True wenn die Rechnung eine Suite8-Stornorechnung ist
    (ZINV_VOID_ZINV_ID verweist auf die stornierte Original-Rechnung)."""
    void_id = (invoice.get("header") or {}).get("zinv_void_zinv_id")
    try:
        return int(void_id or 0) > 0
    except (TypeError, ValueError):
        return False


def is_credit_note(invoice: dict) -> bool:
    """True wenn die Rechnung als XRechnung CreditNote (InvoiceTypeCode=381)
    gerendert werden soll. Heuristik:
    - ZINV_ROLE in (3, 31)  -> offizielle Suite8-Credit-Note
    - Summe der Line-Netto-Betraege < 0  -> de-facto Gutschrift, in der
      Hotel-Praxis die haeufige Form (Suite8-ROLE=0 mit negativen Lines).
      Anzahlungsabbuchungen (is_deposit_line) zaehlen dabei nicht mit.
    - ZINV_VOID_ZINV_ID gesetzt  -> Suite8-Stornorechnung. Sie traegt per ZPIL
      dieselben ZPOS wie das Original mit POSITIVEN Betraegen; ohne diese
      Pruefung ginge sie als zweite Rechnung (380) hinaus.

    Sum exakt 0 zaehlt NICHT als CreditNote (das ist Pfand-Aufhebung,
    wird vom Netto=0-Validator-Check abgefangen).
    """
    header = invoice.get("header") or {}
    role = header.get("zinvrole") or header.get("zinv_role") or 0
    try:
        role_int = int(role)
    except (TypeError, ValueError):
        role_int = 0
    if role_int in (3, 31) or is_void_storno(invoice):
        return True
    # Anzahlungsabbuchungen zaehlen nicht: ein Anzahlungsueberhang auf der
    # Schlussrechnung ist keine Gutschrift.
    lines = [ln for ln in (invoice.get("lines") or []) if not is_deposit_line(ln)]
    try:
        net_sum = sum(float(ln.get("lineextensionamountnet") or 0) for ln in lines)
    except (TypeError, ValueError):
        net_sum = 0.0
    return net_sum < 0
