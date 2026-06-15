"""
slim/scripts/set_password.py
----------------------------
Einmalig-Setup: legt slim/config/connection.key an (Fernet) und
verschluesselt das Oracle-Passwort in slim/config/connection.json.

Aufruf:
  install\\python\\python.exe slim\\scripts\\set_password.py

Prompt fragt das Passwort interaktiv ab (getpass — kein Echo, nicht in
der Shell-History). Liest connection.json (muss existieren), ersetzt
das 'password'-Feld durch das Fernet-Token, schreibt zurueck. Erzeugt
connection.key, wenn sie fehlt.

Fuer skript-gesteuertes Setup (NICHT empfohlen) kann das Passwort
trotzdem als argv[1] uebergeben werden — landet dann allerdings in der
PowerShell-History.
"""
import getpass
import json
import sys
from pathlib import Path

_SLIM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SLIM.parent))

from core.crypto import generate_key_file, load_key, encrypt


def main():
    if len(sys.argv) == 2:
        plaintext = sys.argv[1]
        print("WARNUNG: Passwort wurde per Cmdline uebergeben - "
              "landet in der PowerShell-History.")
    elif len(sys.argv) == 1:
        plaintext = getpass.getpass("Oracle-Passwort: ")
        confirm = getpass.getpass("Bestaetigen:      ")
        if plaintext != confirm:
            print("FEHLER: Passwoerter stimmen nicht ueberein.")
            sys.exit(3)
    else:
        print("Usage: set_password.py            (interaktiv)")
        print("       set_password.py <password> (NICHT empfohlen)")
        sys.exit(1)

    if not plaintext:
        print("FEHLER: Leeres Passwort nicht erlaubt.")
        sys.exit(4)

    config_dir = _SLIM / "config"
    key_path = config_dir / "connection.key"
    conn_path = config_dir / "connection.json"

    if not conn_path.exists():
        print(f"FEHLER: {conn_path} fehlt. Bitte aus .example anlegen.")
        sys.exit(2)

    if not key_path.exists():
        generate_key_file(key_path)
        print(f"Fernet-Key erzeugt: {key_path}")

    key = load_key(key_path)
    cfg = json.loads(conn_path.read_text(encoding="utf-8"))
    cfg["password"] = encrypt(plaintext, key)
    conn_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Passwort verschluesselt in connection.json eingetragen.")


if __name__ == "__main__":
    main()
