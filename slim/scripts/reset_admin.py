"""
slim/scripts/reset_admin.py
---------------------------
Notfall: Verwalter-Zugang am Server zuruecksetzen, wenn das Passwort
vergessen ist und kein anderer Verwalter mehr da ist.

Aufruf (am Server, als Administrator - am einfachsten per reset_admin.cmd):
  install\\python\\python.exe slim\\scripts\\reset_admin.py [Benutzername]

- vorhandener Verwalter:   bekommt ein neues Startpasswort
- vorhandener "ansehen":   wird Verwalter und bekommt ein Startpasswort
- unbekannter Name:        wird als neuer Verwalter angelegt
Das Startpasswort muss bei der naechsten Anmeldung geaendert werden. Alle
anderen Benutzer bleiben unveraendert. Der Vorgang steht im Protokoll.

Bewusst KEIN Web-Endpunkt: Das Skript aendert nur die Datei
slim\\data\\users.json direkt am Server. Ueber eine Netzwerkfreigabe
(\\\\server\\...) gestartet, verweigert es die Ausfuehrung.
"""
import getpass
import sys
from pathlib import Path
from typing import Callable, Optional

_SLIM = Path(__file__).resolve().parent.parent
if str(_SLIM.parent) not in sys.path:
    sys.path.insert(0, str(_SLIM.parent))

from slim.core_slim import audit_jsonl, auth  # noqa: E402


def ist_netzwerkpfad(path) -> bool:
    s = str(path).replace("/", "\\")
    return s.startswith("\\\\")


def reset_admin(store: auth.UserStore, name: str, password: str) -> str:
    """Startpasswort setzen und Verwalter-Rolle sicherstellen.
    Liefert 'zurueckgesetzt' | 'befoerdert' | 'angelegt'."""
    auth._check_password(password)          # vor jeder Aenderung pruefen
    user = store.get(name)
    if user is None:
        store.create(name, password, "verwalten", must_change=True)
        return "angelegt"
    store.set_password(name, password, must_change=True)
    if user.get("role") != "verwalten":
        store.set_role(name, "verwalten")
        return "befoerdert"
    return "zurueckgesetzt"


def main(argv: list, slim_dir=None, ask: Optional[Callable[[str], str]] = None) -> int:
    slim_dir = slim_dir if slim_dir is not None else _SLIM
    ask = ask or getpass.getpass
    if ist_netzwerkpfad(slim_dir) or ist_netzwerkpfad(Path.cwd()):
        print("FEHLER: Dieses Skript darf nur am Server selbst laufen, "
              "nicht ueber eine Netzwerkfreigabe.")
        return 5
    data_dir = Path(slim_dir) / "data"
    store = auth.UserStore(data_dir / "users.json")

    if len(argv) > 1:
        print("Aufruf: reset_admin.py [Benutzername]")
        return 1
    if argv:
        name = argv[0].strip()
    else:
        try:
            vorhanden = store.list()
        except auth.AuthError as e:
            vorhanden = None
            print(f"Hinweis: {e}")
        if vorhanden:
            print("Vorhandene Benutzer:")
            for u in vorhanden:
                print(f"  {u['name']:<30} {u['role']}")
        name = input("Benutzername des Verwalters: ").strip()
    if not name:
        print("FEHLER: Kein Benutzername angegeben.")
        return 1

    pw = ask(f"Neues Startpasswort fuer {name} (mind. {auth.MIN_PASSWORD_LEN} Zeichen): ")
    if pw != ask("Startpasswort wiederholen: "):
        print("FEHLER: Die Passwoerter stimmen nicht ueberein. Nichts geaendert.")
        return 3

    try:
        aktion = reset_admin(store, name, pw)
    except auth.AuthError as e:
        print(f"FEHLER: {e}")
        if "nicht lesbar" in str(e) or "ungueltiges Format" in str(e):
            print("Die Benutzerdatei ist beschaedigt. Datei slim\\data\\users.json "
                  "umbenennen, Dienst neu starten und den ersten Verwalter im "
                  "Browser unter http://127.0.0.1:8022/ neu anlegen.")
        else:
            print("Nichts geaendert.")
        return 4

    audit_jsonl.record_safe(data_dir, "admin_zurueckgesetzt",
                            details={"user": name, "aktion": aktion, "by": "reset_admin (Server)"})
    text = {"zurueckgesetzt": "hat ein neues Startpasswort",
            "befoerdert": "ist jetzt Verwalter und hat ein neues Startpasswort",
            "angelegt": "wurde als Verwalter angelegt"}[aktion]
    print(f"OK: {name} {text}.")
    print("Bei der naechsten Anmeldung muss das Passwort geaendert werden.")
    print("War die Anmeldung nach Fehlversuchen gesperrt: Dienst neu starten "
          "(nssm restart Suite8XRechnungSlim) oder 15 Minuten warten.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
