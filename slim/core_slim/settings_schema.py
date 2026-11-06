"""
slim/core_slim/settings_schema.py
---------------------------------
Beschreibung jeder Einstellung, die die Oberflaeche anbietet: Datei, Schluessel,
Typ, Pruefung, Erklaertext, ob geheim und ob ein Neustart noetig ist.

Die Dateien bleiben, wo sie sind (slim/config/*.json); unbekannte Schluessel
in den Dateien bleiben beim Speichern erhalten.
"""
import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class SettingError(ValueError):
    pass


@dataclass(frozen=True)
class Setting:
    key: str
    file: str
    label: str
    help: str
    type: str = "str"            # str | int | bool | list | select | secret
    restart: bool = False
    choices: tuple = ()
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    check: Optional[Callable[[Any], None]] = None
    default: Any = None


@dataclass(frozen=True)
class Section:
    id: str
    label: str
    settings: tuple = field(default_factory=tuple)


def _regex_with_group(value: str) -> None:
    if not value:
        return
    try:
        rx = re.compile(value)
    except re.error as e:
        raise SettingError(f"kein gueltiger regulaerer Ausdruck ({e})")
    if not ({"zinv_number", "zinv_id"} & set(rx.groupindex)):
        raise SettingError("braucht eine benannte Gruppe (?P<zinv_number>...) oder (?P<zinv_id>...)")


def _attachment_name(value: str) -> None:
    if "{zinv_number}" not in (value or ""):
        raise SettingError("muss {zinv_number} enthalten")


def _ip_list(values: list) -> None:
    for v in values:
        try:
            ipaddress.ip_network(str(v).strip(), strict=False)
        except ValueError:
            raise SettingError(f"{v!r} ist keine IP-Adresse und kein Netz (z. B. 192.168.1.0/24)")


def _gastzeile(value: str) -> None:
    import string
    try:
        names = {f for _, f, _, _ in string.Formatter().parse(value or "") if f is not None}
    except ValueError as e:
        raise SettingError(f"Vorlage ungueltig ({e})")
    unknown = names - {"gast", "zimmer", "anreise", "abreise"}
    if unknown:
        raise SettingError("unbekannte Platzhalter: " + ", ".join(sorted(unknown)))


def _email(value: str) -> None:
    if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise SettingError("keine gueltige E-Mail-Adresse")


C, H, A, U = "connection.json", "hotel.json", "app_settings.json", "update.json"

SECTIONS: tuple[Section, ...] = (
    Section("datenbank", "Datenbank (Suite8)", (
        Setting("tns_alias", C, "TNS-Alias", "Name der Suite8-Datenbank aus der tnsnames.ora, z. B. V8.", restart=True),
        Setting("username", C, "Benutzer", "Oracle-Benutzer, mit dem Slim liest und Anhaenge schreibt.", restart=True),
        Setting("password", C, "Passwort", "Oracle-Passwort. Wird verschluesselt gespeichert und nie angezeigt. Leer lassen = unveraendert.", type="secret", restart=True),
        Setting("tns_admin", C, "Ordner der tnsnames.ora", "Pfad zum Ordner mit tnsnames.ora (TNS_ADMIN).", restart=True),
        Setting("oracle_client_lib_dir", C, "Oracle-Client-Ordner", "Pfad zum 64-bit Oracle Instant Client. Leer = Thin-Modus bzw. automatische Suche.", restart=True),
    )),
    Section("hotel", "Hotel", (
        Setting("hotel_code", H, "Hauskuerzel", "Kurzname des Hauses, erscheint in Protokoll und Archiv."),
        Setting("currency", H, "Waehrung", "Ersatzwaehrung, wenn Suite8 keine Basiswaehrung liefert (ISO, z. B. EUR).", default="EUR"),
        Setting("default_payment_terms_days", H, "Zahlungsziel (Tage)", "Tage bis zur Faelligkeit, falls Suite8 kein Zahlungsziel liefert.", type="int", minimum=0, maximum=365, default=14),
        Setting("seller_contact_name", H, "Ansprechpartner", "Name im Verkaeuferkontakt (BT-41), wenn Suite8 keinen liefert.", default="Buchhaltung"),
        Setting("seller_contact_phone", H, "Telefon Ansprechpartner", "Telefon im Verkaeuferkontakt (BT-42), wenn Suite8 keines liefert."),
        Setting("seller_contact_email", H, "E-Mail Ansprechpartner", "E-Mail im Verkaeuferkontakt (BT-43), wenn Suite8 keine liefert.", check=_email),
    )),
    Section("versand", "Versand", (
        Setting("absender_email", H, "Absender-E-Mail", "Absenderadresse der Rechnungsmails.", check=_email),
        Setting("suite8_recognize_subject_pattern", H, "Erkennung im Betreff", "Regulaerer Ausdruck, der die Rechnungsnummer aus dem Mail-Betreff liest, mit (?P<zinv_number>...).", check=_regex_with_group),
        Setting("suite8_recognize_filename_pattern", H, "Erkennung im Dateinamen", "Regulaerer Ausdruck fuer den PDF-Dateinamen, mit (?P<zinv_number>...) oder (?P<zinv_id>...). Leer = nicht verwendet.", check=_regex_with_group),
        Setting("suite8_poll_interval_seconds", H, "Abrufintervall (Sekunden)", "Wie oft Slim nach neuen Rechnungsmails sucht.", type="int", minimum=5, maximum=3600, restart=True, default=30),
        Setting("suite8_attachment_name_template", H, "Name des XML-Anhangs", "Dateiname der XRechnung, muss {zinv_number} enthalten.", check=_attachment_name, default="{zinv_number}.xml"),
        Setting("xml_only_all", H, "Nur XML fuer alle", "Ein: Jede Rechnungsmail enthaelt nur die XRechnung, PDF und RTF werden aus der Mail genommen.", type="bool", default=False),
        Setting("xml_only_membership", H, "Membership fuer Nur-XML", "Kurzbezeichnung des Suite8-Memberships, mit dem ein Rechnungsempfaenger nur die XRechnung bekommt. Leer = aus.", default="PDF"),
    )),
    Section("inhalt", "Rechnungsinhalt", (
        Setting("gastzeile", H, "Gastzeile (BT-22)", "Hinweis bei genau einem Gast. Platzhalter {gast}, {zimmer}, {anreise}, {abreise}. Leer = keine Gastzeile.", check=_gastzeile, default="Gast: {gast}, Zimmer {zimmer}, {anreise} bis {abreise}"),
        Setting("positionen_zusammenfassen", H, "Positionen zusammenfassen", "Gleiche Buchungen (gleicher Gast, Zimmer, Artikel, Preis) als eine Position mit Menge ausweisen.", type="bool", default=True),
        Setting("auslagen_artikel", H, "Auslage-Artikel", "Suite8-Artikel (Kurzname), die ohne Steuerbuchung als Auslage mit 0 % gelten. Andere Artikel ohne Steuerbuchung blockieren die Rechnung.", type="list", default=["AUS", "DUR"]),
    )),
    Section("pruefung", "Pruefung", (
        Setting("kosit_validation", A, "KoSIT-Pruefung", "Jede XRechnung vor dem Versand mit dem KoSIT-Validator pruefen.", type="bool", default=True),
        Setting("xrechnung_version", A, "XRechnung-Version", "Version der Pruefregeln.", type="select", choices=("3.0.2",), default="3.0.2"),
    )),
    Section("server", "Server", (
        Setting("host", A, "Adresse", "127.0.0.1 = nur am Server erreichbar, 0.0.0.0 = im Netzwerk (dann erlaubte Adressen pflegen).", type="select", choices=("127.0.0.1", "0.0.0.0"), restart=True, default="127.0.0.1"),
        Setting("port", A, "Port", "Port der Oberflaeche.", type="int", minimum=1, maximum=65535, restart=True, default=8022),
        Setting("allowed_ips", A, "Erlaubte Adressen", "IP-Adressen oder Netze (z. B. 192.168.1.0/24), die die Oberflaeche erreichen duerfen. localhost ist immer erlaubt.", type="list", restart=True, check=_ip_list, default=[]),
        Setting("log_level", A, "Protokoll-Stufe", "Ausfuehrlichkeit der Logdatei.", type="select", choices=("DEBUG", "INFO", "WARNING", "ERROR"), restart=True, default="INFO"),
        Setting("audit_retention_months", A, "Aufbewahrung Protokoll (Monate)", "Wie lange Audit-Eintraege aufbewahrt werden.", type="int", minimum=1, maximum=240, default=24),
    )),
    Section("update", "Update", (
        Setting("enabled", U, "Automatische Updates", "Neue Versionen von GitHub einspielen.", type="bool", default=True),
        Setting("owner", U, "GitHub-Besitzer", "Besitzer des Repositorys.", default="ahornhotels"),
        Setting("repo", U, "GitHub-Repository", "Name des Repositorys.", default="XRechnung_Slim"),
        Setting("pat_token", U, "Zugriffstoken", "Nur noetig, wenn das Repository privat ist (Leserecht auf Inhalte). Wird verschluesselt gespeichert und nie angezeigt. Leer lassen = unveraendert.", type="secret"),
    )),
)


def section(section_id: str) -> Section:
    for s in SECTIONS:
        if s.id == section_id:
            return s
    raise KeyError(section_id)


def coerce(setting: Setting, value: Any) -> Any:
    """Wandelt einen Eingabewert in den gespeicherten Typ und prueft ihn.
    Wirft SettingError mit verstaendlicher Meldung."""
    t = setting.type
    if t == "bool":
        if isinstance(value, bool):
            v = value
        elif str(value).strip().lower() in ("1", "true", "ja", "an", "on"):
            v = True
        elif str(value).strip().lower() in ("0", "false", "nein", "aus", "off", ""):
            v = False
        else:
            raise SettingError("ja oder nein erwartet")
    elif t == "int":
        try:
            v = int(str(value).strip())
        except (TypeError, ValueError):
            raise SettingError("ganze Zahl erwartet")
        if setting.minimum is not None and v < setting.minimum:
            raise SettingError(f"mindestens {setting.minimum}")
        if setting.maximum is not None and v > setting.maximum:
            raise SettingError(f"hoechstens {setting.maximum}")
    elif t == "list":
        items = value if isinstance(value, list) else str(value or "").replace("\n", ",").split(",")
        v = [str(i).strip() for i in items if str(i).strip()]
    elif t == "select":
        v = str(value)
        if v not in setting.choices:
            raise SettingError("erlaubt: " + ", ".join(setting.choices))
    else:
        v = "" if value is None else str(value).strip()
        if len(v) > 500:
            raise SettingError("hoechstens 500 Zeichen")
    if setting.check:
        setting.check(v)
    return v
