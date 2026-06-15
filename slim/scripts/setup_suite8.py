"""
slim/scripts/setup_suite8.py
----------------------------
Interaktives Suite8-Setup fuer die Slim-App.

Prueft:
  1. Standard-Hotel-Stammdaten in WUSS (read-only Pruefung, meldet Luecken)
  2. Drei XRechnung-spezifische UDEF-Keys in WUSS
     - UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE
     - UDEF_XRECHNUNG_RESPONSIBLE_NAME
     - UDEF_XRECHNUNG_FIRMIERUNG  (optional)
  3. Optional: Leitweg-ID-XMTY-Eintrag (B2G, nur wenn benoetigt)
  4. Gibt SQL fuer den BLOCKSEND-Trigger zum Copy-Paste aus

Schreibt INSERTs in WUSS wenn Keys fehlen. Existierende Eintraege werden
NICHT ueberschrieben. Bei fehlenden Schreibrechten wird das SQL zum Copy-
Paste an einen DBA ausgegeben.

Aufruf:
  install\\python\\python.exe slim\\scripts\\setup_suite8.py
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
_SLIM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
os.environ.setdefault("SUITE8_CONFIG_DIR", str(_SLIM / "config"))

from core.db_connector import get_connection
from core.config_loader import load_hotel_config


# Standard-Hotel-Stammdaten — werden NICHT angelegt (Suite8 setzt sie beim
# Hotel-Setup), aber wir pruefen, ob sie vorhanden sind, und melden Luecken.
REQUIRED_STANDARD = [
    ("HotelCode",      "Hotel-Code (SupplierID in XRechnung)"),
    ("Hotelid",        "Hotel-Name (SupplierName)"),
    ("HotelAddress",   "Strasse + Hausnummer"),
    ("Hotelcity",      "Ort"),
    ("Hotelzipcode",   "PLZ"),
    ("Hotelcountry",   "Land (Langname, wird auf ISO2 aufgeloest)"),
    ("HotelTaxNumber", "USt-IdNr."),
    ("Hoteltel",       "Telefon"),
    ("Hotelemail",     "Hotel-E-Mail"),
    ("HotelbankIBAN",  "IBAN"),
    ("HotelbankBIC",   "BIC"),
    ("BaseCurrency",   "Basis-Waehrung (ZCUR_ID)"),
]


# UDEF-Keys, die fuer die XRechnung gebraucht werden.
# Format: (Key-Name, Default, Prompt, Pflicht?)
UDEF_XRECHNUNG = [
    ("UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE",
     "14",
     "Tage bis Faelligkeit nach Rechnungsdatum",
     True),
    ("UDEF_XRECHNUNG_RESPONSIBLE_NAME",
     "Buchhaltung",
     "Ansprechpartner Buchhaltung (BR-DE-5 erforderlich)",
     True),
    ("UDEF_XRECHNUNG_FIRMIERUNG",
     "",
     "Offizielle Firmierung (leer = Hotelid wird verwendet)",
     False),
]


def _print_header(title):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def _check_standard_wuss(cur) -> list[tuple[str, str]]:
    """Liefert Liste der fehlenden Standard-Keys (Pflicht-Stammdaten)."""
    missing = []
    for name, desc in REQUIRED_STANDARD:
        cur.execute(
            "SELECT wuss_value FROM wuss WHERE wuss_xcms_id=0 AND wuss_name=:n",
            {"n": name},
        )
        row = cur.fetchone()
        val = (row[0] or "").strip() if row else ""
        status = "OK " if val else "FEHLT"
        print(f"  [{status}] {name:18s} {desc}")
        if not val:
            missing.append((name, desc))
    return missing


def _check_udef(cur) -> list[tuple]:
    """Liefert Liste der fehlenden UDEF-Keys (Tupel wie in UDEF_XRECHNUNG)."""
    missing = []
    for name, default, prompt, required in UDEF_XRECHNUNG:
        cur.execute(
            "SELECT wuss_value FROM wuss WHERE upper(wuss_name) = upper(:n)",
            {"n": name},
        )
        row = cur.fetchone()
        present = row is not None
        existing_val = (row[0] or "").strip() if row else ""
        tag = "OK   " if present else "FEHLT"
        opt = "" if required else "  (optional)"
        existing_str = f"  = {existing_val!r}" if existing_val else ""
        print(f"  [{tag}] {name}{opt}{existing_str}")
        if not present:
            missing.append((name, default, prompt, required))
    return missing


def _ask_values(missing: list[tuple]) -> list[tuple[str, str]]:
    """Fragt fuer jeden fehlenden Key interaktiv den Wert ab.

    Liefert nur Eintraege zurueck, die tatsaechlich gesetzt werden sollen
    (Pflichtfelder muessen, optionale duerfen leer bleiben → werden
    uebersprungen).
    """
    results = []
    for name, default, prompt, required in missing:
        print()
        marker = "(Pflicht)" if required else "(optional, leer = ueberspringen)"
        suggestion = f" [{default}]" if default else ""
        try:
            val = input(f"  {prompt} {marker}{suggestion}: ").strip()
        except EOFError:
            print()
            print("  EOF — keine Eingabe moeglich (non-interaktiv ausgefuehrt?).")
            print("  Re-Lauf interaktiv: install\\python\\python.exe slim\\scripts\\setup_suite8.py")
            sys.exit(2)
        if not val:
            val = default
        if not val and required:
            print(f"  -> {name}: Pflichtwert, kein Default — uebersprungen, "
                  f"bitte spaeter manuell anlegen")
            continue
        if not val:
            continue
        if len(val) > 60:
            print(f"  WARNUNG: Wert wird auf 60 Zeichen gekuerzt "
                  f"(WUSS_VALUE.max = 60)")
            val = val[:60]
        results.append((name, val))
    return results


def _try_insert(cur, conn, name: str, value: str) -> bool:
    """INSERT INTO wuss mit SEQ_WUSS.NEXTVAL. Bei Erfolg True, sonst False
    (Permission-Fehler etc.).
    """
    try:
        cur.execute(
            "INSERT INTO wuss (wuss_id, wuss_xcms_id, wuss_name, wuss_value) "
            "VALUES (seq_wuss.nextval, 0, :n, :v)",
            {"n": name, "v": value},
        )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"  -> INSERT fehlgeschlagen: {e}")
        return False


def _print_dba_sql(inserts: list[tuple[str, str]]) -> None:
    print()
    print("Bitte folgendes SQL als DBA / V8LIVE-Admin ausfuehren:")
    print()
    print("-" * 72)
    for name, value in inserts:
        safe_v = value.replace("'", "''")
        print(f"INSERT INTO wuss (wuss_id, wuss_xcms_id, wuss_name, wuss_value)")
        print(f"VALUES (seq_wuss.nextval, 0, '{name}', '{safe_v}');")
    print("COMMIT;")
    print("-" * 72)


def _print_trigger_sql() -> None:
    """Render BLOCKSEND-Trigger-SQL fuer den DBA."""
    try:
        cfg = load_hotel_config()
        fn_pat = cfg.get("suite8_recognize_filename_pattern", "") or ""
    except Exception:
        fn_pat = ""

    print()
    print("Damit der Suite8-Mailservice die Folio-Mails NICHT sofort sendet")
    print("(damit der Slim-Poller die XRechnung als Anhang dranhaengen kann),")
    print("muss eine WMAI mit BLOCKSEND=1 erzeugt werden. Das passiert ueber")
    print("einen DB-Trigger. Bitte folgendes SQL als V8LIVE / DBA ausfuehren:")
    print()
    safe = (fn_pat or r"Folio.*\.pdf$").replace("'", "''")
    print("-" * 72)
    print(f"""\
CREATE OR REPLACE TRIGGER WMAI_XRECHNUNG_BLOCK
BEFORE INSERT OR UPDATE OF WMAI_NO_OF_ATTEMPTS, WMAI_SENT
ON WMAI
FOR EACH ROW
WHEN (NEW.WMAI_SENT = 0)
BEGIN
  IF :NEW.WMAI_ATTACHMENT_FILE_NAME IS NOT NULL
     AND REGEXP_LIKE(:NEW.WMAI_ATTACHMENT_FILE_NAME, '{safe}', 'i') THEN
    :NEW.WMAI_BLOCKSEND := 1;
  END IF;
END;
/""")
    print("-" * 72)
    if not fn_pat:
        print()
        print("HINWEIS: Du nutzt das Subject-Pattern statt Filename-Pattern.")
        print("         Dann muss der Trigger auf WMAI_SUBJECT pruefen, nicht")
        print("         auf WMAI_ATTACHMENT_FILE_NAME. Passe das SQL entsprechend an.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="Nur pruefen, keine INSERTs / keine Eingaben")
    args = parser.parse_args()

    _print_header("Suite8 Slim-Setup: Stammdaten + UDEF-Keys"
                  + (" [CHECK-ONLY]" if args.check else ""))

    with get_connection() as conn:
        cur = conn.cursor()
        _print_header("1) Standard-Hotel-Stammdaten in WUSS")
        missing_std = _check_standard_wuss(cur)
        if missing_std:
            print()
            print("Diese Standard-Keys fehlen — sie werden NORMALERWEISE beim")
            print("Suite8-Hotel-Setup gepflegt (Configuration → Property →")
            print("Property Information). Bitte dort vervollstaendigen, sonst")
            print("schlaegt die XRechnung-Validierung mit fehlenden Pflichtfeldern fehl.")

        _print_header("2) UDEF_XRECHNUNG_*-Keys")
        missing_udef = _check_udef(cur)

        if args.check:
            _print_header("Check-Modus: keine Aenderungen")
            print(f"  Hotel-Stammdaten: {len(missing_std)} fehlen")
            print(f"  UDEF-Keys:        {len(missing_udef)} fehlen")
            print("Fuer interaktives Anlegen: ohne --check ausfuehren.")
            return

        if missing_udef:
            _print_header("3) Werte fuer fehlende UDEF-Keys eingeben")
            print("(Enter ohne Eingabe = Default uebernehmen.")
            print(" Werte koennen jederzeit per UPDATE in WUSS geaendert werden.)")
            to_insert = _ask_values(missing_udef)

            if to_insert:
                _print_header("4) INSERT in WUSS")
                inserted = []
                blocked = []
                for name, value in to_insert:
                    print(f"  Inserting {name} = {value!r} ...")
                    if _try_insert(cur, conn, name, value):
                        inserted.append((name, value))
                    else:
                        blocked.append((name, value))

                if inserted:
                    print()
                    print(f"  {len(inserted)} Key(s) erfolgreich angelegt.")
                if blocked:
                    print()
                    print(f"  {len(blocked)} Key(s) konnten nicht angelegt werden")
                    print("  (vermutlich fehlende INSERT-Rechte auf WUSS).")
                    _print_dba_sql(blocked)
        else:
            print()
            print("Alle UDEF_XRECHNUNG_*-Keys vorhanden — nichts zu tun.")

        _print_header("5) BLOCKSEND-Trigger fuer den Suite8-Mailservice")
        _print_trigger_sql()

    _print_header("Fertig")
    print("Naechste Schritte:")
    print("  - slim/config/hotel.json ueberpruefen / anpassen")
    print("  - Pattern im Slim-Backend testen (http://127.0.0.1:8022/)")
    print("  - Service starten: slim/install/install_slim.cmd")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print("Abgebrochen.")
        sys.exit(130)
