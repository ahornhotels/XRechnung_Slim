"""
slim/core_slim/settings_schema.py
---------------------------------
Beschreibung jeder Einstellung, die die Oberfläche anbietet: Datei, Schlüssel,
Typ, Prüfung, Erklärtext, ob geheim und ob ein Neustart nötig ist.

Die Dateien bleiben, wo sie sind (slim/config/*.json); unbekannte Schlüssel
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
    info: str = ""               # ausfuehrliche Erklaerung (HTML aus diesem Modul) hinter dem (!)-Knopf


@dataclass(frozen=True)
class Section:
    id: str
    label: str
    settings: tuple = field(default_factory=tuple)
    page: str = ""               # Menuepunkt: xrechnung | hotel | system


def _regex_with_group(value: str) -> None:
    """Gleiche Regel wie Setup-Wizard und Pattern-Seite: kompilierbar und GENAU
    eine der Gruppen (?P<zinv_number>...) / (?P<zinv_id>...)."""
    if not value:
        return
    from modules.suite8_pattern import PatternMatchError, validate_pattern
    try:
        validate_pattern(value)
    except PatternMatchError as e:
        raise SettingError(str(e))


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
        raise SettingError(f"Vorlage ungültig ({e})")
    unknown = names - {"gast", "zimmer", "anreise", "abreise"}
    if unknown:
        raise SettingError("unbekannte Platzhalter: " + ", ".join(sorted(unknown)))


def _github_name(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value or "") or ".." in value:
        raise SettingError("nur Buchstaben, Ziffern, Punkt, Bindestrich, Unterstrich (max. 100)")


def _kanal(value: str) -> None:
    """Update-Kanal: leer = Standard, sonst ein kurzer Name wie AHORN."""
    if value and not re.fullmatch(r"[A-Za-z0-9]{1,30}", value):
        raise SettingError("nur Buchstaben und Ziffern (max. 30), leer = Standard")


def _local_dir(value: str) -> None:
    """Nur lokale absolute Ordner: Aus dem Client-Ordner lädt Slim
    Programmbibliotheken, ein Netzwerkpfad wäre ein Einfallstor."""
    if not value:
        return
    v = value.replace("/", "\\")
    if v.startswith("\\\\") or not re.match(r"^[A-Za-z]:\\", v):
        raise SettingError(r"lokaler absoluter Ordner erwartet (z. B. C:\oracle\instantclient), kein Netzwerkpfad")


def _email(value: str) -> None:
    if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise SettingError("keine gültige E-Mail-Adresse")


C, H, A, U = "connection.json", "hotel.json", "app_settings.json", "update.json"

_INFO_RUNDUNGSAUSGLEICH = """
<h3>Warum es den Rundungsausgleich gibt</h3>
<p><b>So rechnet Suite8:</b> Die Preise sind Bruttopreise. Zu jeder einzelnen
Buchung bucht Suite8 eine eigene Steuerbuchung und rundet sie auf den Cent –
jede Buchung ist für Journal und Tagesabschluss in sich abgeschlossen.</p>
<p><b>Beispiel:</b> 67 × Frühstück zu 3,85 € brutto mit 19 %. Genau wären es je
Buchung 0,6147 € Steuer, gerundet 0,61 € (netto 3,24 €). Zusammen
<b>40,87 € Steuer</b>. Rechnet man die Steuer einmal auf die Summe
(257,95 € × 19 / 119), sind es <b>41,19 €</b>. Die 0,32 € entstehen nur durch
das Runden je Buchung.</p>
<p><b>Was die XRechnung verlangt:</b> Je Steuersatz muss die
Bemessungsgrundlage genau der Summe der Positionen entsprechen (Regel BR-S-08)
und die Steuer genau Bemessungsgrundlage × Steuersatz sein (BR-CO-17). Der
KoSIT-Validator lässt bis zu 1 € Abweichung durch und meldet deshalb
„gültig“. Strenge Empfänger wie <b>SAP</b> prüfen auf den Cent und lehnen die
Rechnung ab.</p>

<h3>Die drei Einstellungen</h3>
<ul>
<li><b>aus</b> – die XRechnung übernimmt die Werte aus Suite8 unverändert. Die
Regeln BR-S-08/BR-CO-17 sind dann um Cent verletzt, strenge Empfänger lehnen
ab.</li>
<li><b>position</b> – je Steuersatz rechnet Slim vom Brutto aus: Steuer =
Brutto × Satz / (100 + Satz), einmal gerundet; Bemessungsgrundlage = Brutto −
Steuer. Den Rest von wenigen Cent bekommt die <b>größte Position</b> des
Steuersatzes (ihr Einzelpreis wird 4-stellig angepasst). Im Beispiel:
Frühstück 216,76 € statt 217,08 €.</li>
<li><b>abschlag</b> (Standard) – dieselbe Rechnung, aber alle Positionen bleiben wie in
Suite8. Der Rest steht als eigener <b>Abschlag bzw. Zuschlag
„Rundungsausgleich“</b> mit dem Steuersatz in der Rechnung. Im Beispiel:
Frühstück 217,08 € und Abschlag 0,32 €.</li>
</ul>
<p><b>position oder abschlag?</b> Beide liefern dieselbe Steuer und denselben
Endbetrag. „position“ ist unauffälliger, ändert aber eine Position um Cent.
„abschlag“ lässt alle Positionen unverändert und zeigt die Differenz offen als
eigene Zeile.</p>

<h3>Ergebnis: Datenbank, PDF und XML im Vergleich</h3>
<table>
<tr><th></th><th>Datenbank (Suite8)</th><th>PDF-Rechnung</th><th>XML „aus“</th><th>XML „position“</th><th>XML „abschlag“</th></tr>
<tr><th>Endbetrag</th><td>Suite8</td><td>wie Suite8</td><td>wie Suite8</td><td>wie Suite8</td><td>wie Suite8</td></tr>
<tr><th>Steuer</th><td>Summe der Steuerbuchungen</td><td>wie Suite8</td><td>je Buchung gerundet</td><td>je Satz neu berechnet, weicht um Cent ab</td><td>je Satz neu berechnet, weicht um Cent ab</td></tr>
<tr><th>Positionen netto</th><td>Suite8</td><td>wie Suite8</td><td>wie Suite8</td><td>eine Position je Satz um Cent geändert</td><td>wie Suite8</td></tr>
<tr><th>Zusätzliche Zeile</th><td>–</td><td>–</td><td>–</td><td>–</td><td>„Rundungsausgleich“ je Satz</td></tr>
<tr><th>Strenge Prüfung (z. B. SAP)</th><td>–</td><td>–</td><td>Ablehnung möglich</td><td>angenommen</td><td>angenommen</td></tr>
</table>

<h3>Was das für die Buchhaltung heißt</h3>
<ul>
<li>Slim ändert <b>nichts in Suite8</b>: Buchungen, Journal und PDF bleiben,
wie sie sind. Nur die XRechnung wird anders gerechnet.</li>
<li>Die Steuer in der XRechnung kann daher je Rechnung um einige Cent von den
Suite8-Steuerbuchungen abweichen, mal nach oben, mal nach unten.</li>
<li>Bei einer E-Rechnung ist die XRechnung das maßgebliche Dokument. Weist sie
mehr Steuer aus als gebucht, wird der ausgewiesene Betrag geschuldet
(§ 14c UStG). Es geht um Cent, sollte aber vor dem Einschalten mit
Buchhaltung bzw. Steuerberatung abgestimmt werden.</li>
<li>Die saubere Lösung an der Quelle wäre, dass Suite8 die Steuer je Rechnung
und Steuersatz statt je Buchung rechnet. Das ist eine Frage an den
Suite8-Support.</li>
</ul>
"""


_INFO_BT10 = """
<h3>Woher die Käuferreferenz (BT-10) kommt</h3>
<ol>
<li><b>DXR-Mitgliedschaft</b> am Rechnungsempfänger – standardmäßig wird zuerst
dieser Wert genommen (<b>Leitweg-ID bzw. Käuferreferenz</b>), wenn gefüllt. Sie hat
immer Vorrang.</li>
<li><b>Freitext 1 bis 4</b> aus dem Rechnungsfenster – nur die hier eingeschalteten.
Die DXR-Mitgliedschaft hat immer Vorrang. Danach gilt der erste gefüllte eingeschaltete
Freitext, in der Reihenfolge 1 → 4.</li>
<li>Ist keiner gefüllt, steht wie bisher der Name des Profils in BT-10.</li>
</ol>
<h3>Wo stehen die Freitexte in Suite8?</h3>
<p>Rechtsklick im Rechnungsfenster → „Bearbeite gewähltes Fenster“ → Reiter „Text“.
Die vier Zeilen dort sind Freitext 1 bis 4.</p>
<h3>Was davon steht sonst in der XRechnung?</h3>
<ul>
<li><b>Freitext 1</b> erscheint immer als Hinweis (BT-22) in der XRechnung,
eingeschaltet zusätzlich als Käuferreferenz.</li>
<li><b>Freitext 2 bis 4</b> erscheinen nur in der XRechnung, wenn sie hier eingeschaltet
sind – dann als Käuferreferenz.</li>
</ul>
"""


SECTIONS: tuple[Section, ...] = (
    Section("erkennung", "Erkennung und Anhang", (
        Setting("suite8_recognize_subject_pattern", H, "Erkennung im Betreff", "Regulärer Ausdruck, der die Rechnungsnummer aus dem Mail-Betreff liest, mit (?P<zinv_number>...).", check=_regex_with_group, default=r"Rechnung\s+Nr\.?\s*(?P<zinv_number>\d+)"),
        Setting("suite8_recognize_filename_pattern", H, "Erkennung im Dateinamen", "Regulärer Ausdruck für den PDF-Dateinamen, mit (?P<zinv_number>...) oder (?P<zinv_id>...). Leer = nicht verwendet.", check=_regex_with_group, default=""),
        Setting("suite8_attachment_name_template", H, "Name des XML-Anhangs", "Dateiname der XRechnung, muss {zinv_number} enthalten.", check=_attachment_name, default="{zinv_number}.xml"),
        Setting("xml_only_all", H, "Nur XML für alle", "Ein: Jede Rechnungsmail enthält nur die XRechnung, PDF und RTF werden aus der Mail genommen.", type="bool", default=False),
        Setting("xml_only_membership", H, "Membership für Nur-XML", "Kurzbezeichnung des Suite8-Memberships, mit dem ein Rechnungsempfänger nur die XRechnung bekommt. Leer = aus.", default="PDF"),
        Setting("freigabe_nach_tagen", H, "Ohne XRechnung freigeben nach (Tagen)", "Rechnungsmails, die so viele Tage (nach Hoteldatum) noch gesperrt sind (z. B. weil die XRechnung fehlerhaft ist und sich niemand gekümmert hat), gibt Slim frei: Suite8 verschickt sie dann ohne XRechnung, nur mit PDF. Gesucht wird bis 7 Tage darüber hinaus, ältere Mails bleiben gesperrt. Jede Freigabe steht im Protokoll. 0 = nie freigeben. Gilt nicht, solange XRechnung ausgeschaltet ist.", type="int", minimum=0, maximum=365, default=0),
    ), page="xrechnung"),
    Section("inhalt", "Rechnungsinhalt", (
        Setting("gastzeile", H, "Gastzeile (BT-22)", "Hinweis bei genau einem Gast. Platzhalter {gast}, {zimmer}, {anreise}, {abreise}. Leer = keine Gastzeile.", check=_gastzeile, default="Gast: {gast}, Zimmer {zimmer}, {anreise} bis {abreise}"),
        Setting("positionen_zusammenfassen", H, "Positionen zusammenfassen", "Gleiche Buchungen (gleicher Gast, Zimmer, Artikel, Preis) als eine Position mit Menge ausweisen.", type="bool", default=True),
        Setting("auslagen_artikel", H, "Auslage-Artikel", "Suite8-Artikel (Kurzname), die ohne Steuerbuchung als Auslage mit 0 % gelten. Andere Artikel ohne Steuerbuchung blockieren die Rechnung.", type="list", default=["AUS", "DUR"]),
        Setting("rundungsausgleich", H, "Rundungsausgleich je Steuersatz", "Suite8 rundet die Steuer je Buchung, dadurch passen Bemessung und Steuer nicht exakt zu den Positionen (manche Empfänger wie SAP lehnen das ab). abschlag (Standard) = Rest als Abschlag/Zuschlag „Rundungsausgleich“, alle Positionen wie in Suite8. position = Steuer je Satz vom Brutto neu, Rest von wenigen Cent in der größten Position. aus = Werte wie aus Suite8, kann von strengen Empfängern abgelehnt werden. Endbetrag bleibt immer gleich, die Steuer kann um Cent von Suite8 abweichen.", type="select", choices=("aus", "position", "abschlag"), default="abschlag", info=_INFO_RUNDUNGSAUSGLEICH),
    ), page="xrechnung"),
    Section("kaeuferreferenz", "Käuferreferenz (BT-10)", (
        Setting("bt10_freitext1", H, "Freitext 1", "Standardmäßig wird zuerst der Wert aus der DXR-Mitgliedschaft genommen (Leitweg-ID bzw. Käuferreferenz), wenn gefüllt – erst danach die eingeschalteten Freitexte. Erscheint immer als Hinweis (BT-22) in der XRechnung, eingeschaltet zusätzlich als Käuferreferenz.", type="bool", default=False, info=_INFO_BT10),
        Setting("bt10_freitext2", H, "Freitext 2", "Standardmäßig wird zuerst der Wert aus der DXR-Mitgliedschaft genommen (Leitweg-ID bzw. Käuferreferenz), wenn gefüllt – erst danach die eingeschalteten Freitexte. Erscheint nur in der XRechnung, wenn hier eingeschaltet – dann als Käuferreferenz.", type="bool", default=False, info=_INFO_BT10),
        Setting("bt10_freitext3", H, "Freitext 3", "Standardmäßig wird zuerst der Wert aus der DXR-Mitgliedschaft genommen (Leitweg-ID bzw. Käuferreferenz), wenn gefüllt – erst danach die eingeschalteten Freitexte. Erscheint nur in der XRechnung, wenn hier eingeschaltet – dann als Käuferreferenz.", type="bool", default=False, info=_INFO_BT10),
        Setting("bt10_freitext4", H, "Freitext 4", "Standardmäßig wird zuerst der Wert aus der DXR-Mitgliedschaft genommen (Leitweg-ID bzw. Käuferreferenz), wenn gefüllt – erst danach die eingeschalteten Freitexte. Erscheint nur in der XRechnung, wenn hier eingeschaltet – dann als Käuferreferenz.", type="bool", default=False, info=_INFO_BT10),
    ), page="xrechnung"),
    Section("pruefung", "Prüfung", (
        Setting("kosit_validation", A, "KoSIT-Prüfung", "Jede XRechnung vor dem Versand mit dem KoSIT-Validator prüfen.", type="bool", default=True),
        Setting("xrechnung_version", A, "XRechnung-Version", "Version der Prüfregeln.", type="select", choices=("3.0.2",), default="3.0.2"),
    ), page="xrechnung"),
    Section("hotel", "Haus", (
        Setting("hotel_code", H, "Hauskürzel", "Kurzname des Hauses, erscheint in Protokoll und Archiv."),
        Setting("hotel_long_name", H, "Hausname", "Ausgeschriebener Name des Hauses, erscheint in der Statusanzeige, wenn kein Hauskürzel gesetzt ist."),
        Setting("currency", H, "Währung", "Ersatzwährung, wenn Suite8 keine Basiswährung liefert (ISO, z. B. EUR).", default="EUR"),
        Setting("default_payment_terms_days", H, "Zahlungsziel (Tage)", "Tage bis zur Fälligkeit, falls Suite8 kein Zahlungsziel liefert.", type="int", minimum=0, maximum=365, default=14),
    ), page="hotel"),
    Section("ansprechpartner", "Ansprechpartner und Absender", (
        Setting("seller_contact_name", H, "Ansprechpartner", "Name im Verkäuferkontakt (BT-41), wenn Suite8 keinen liefert.", default="Buchhaltung"),
        Setting("seller_contact_phone", H, "Telefon Ansprechpartner", "Telefon im Verkäuferkontakt (BT-42), wenn Suite8 keines liefert."),
        Setting("seller_contact_email", H, "E-Mail Ansprechpartner", "E-Mail im Verkäuferkontakt (BT-43), wenn Suite8 keine liefert.", check=_email),
        Setting("absender_email", H, "Absender-E-Mail", "Absenderadresse der Rechnungsmails.", check=_email),
    ), page="hotel"),
    Section("datenbank", "Datenbank (Suite8)", (
        Setting("tns_alias", C, "TNS-Alias", "Name der Suite8-Datenbank aus der tnsnames.ora, z. B. V8.", restart=True),
        Setting("username", C, "Benutzer", "Oracle-Benutzer, mit dem Slim liest und Anhänge schreibt.", restart=True),
        Setting("password", C, "Passwort", "Oracle-Passwort. Wird verschlüsselt gespeichert und nie angezeigt. Leer lassen = unverändert.", type="secret", restart=True),
        Setting("tns_admin", C, "Ordner der tnsnames.ora", "Ordner mit tnsnames.ora (TNS_ADMIN), auch ein Netzwerkordner.", restart=True),
        Setting("oracle_client_lib_dir", C, "Oracle-Client-Ordner", "Lokaler Ordner des 64-bit Oracle Instant Client. Leer = Thin-Modus bzw. automatische Suche.", restart=True, check=_local_dir),
    ), page="system"),
    Section("abruf", "Abruf", (
        Setting("suite8_poll_interval_seconds", H, "Abrufintervall (Sekunden)", "Wie oft Slim nach neuen Rechnungsmails sucht.", type="int", minimum=5, maximum=3600, restart=True, default=30),
    ), page="system"),
    Section("server", "Server", (
        Setting("host", A, "Adresse", "127.0.0.1 = nur am Server erreichbar, 0.0.0.0 = im Netzwerk (dann erlaubte Adressen pflegen).", type="select", choices=("127.0.0.1", "0.0.0.0"), restart=True, default="127.0.0.1"),
        Setting("port", A, "Port", "Port der Oberfläche.", type="int", minimum=1, maximum=65535, restart=True, default=8022),
        Setting("allowed_ips", A, "Erlaubte Adressen", "IP-Adressen oder Netze (z. B. 192.168.1.0/24), die die Oberfläche erreichen dürfen. localhost ist immer erlaubt.", type="list", restart=True, check=_ip_list, default=[]),
        Setting("log_level", A, "Protokoll-Stufe", "Ausführlichkeit der Logdatei.", type="select", choices=("DEBUG", "INFO", "WARNING", "ERROR"), restart=True, default="INFO"),
        Setting("audit_retention_months", A, "Aufbewahrung Protokoll (Monate)", "Wie lange Audit-Einträge aufbewahrt werden.", type="int", minimum=1, maximum=240, default=24),
    ), page="system"),
    Section("update", "Update", (
        Setting("enabled", U, "Automatische Updates", "Neue Versionen von GitHub einspielen.", type="bool", default=True),
        Setting("owner", U, "GitHub-Besitzer", "Besitzer des Repositorys.", default="ahornhotels", check=_github_name),
        Setting("repo", U, "GitHub-Repository", "Name des Repositorys.", default="XRechnung_Slim", check=_github_name),
        Setting("channel", U, "Update-Kanal", "Leer = Standard. Ein Name wie AHORN holt nur die Versionen dieses Kanals (Standard plus Zusätze für diese Häuser).", default="", check=_kanal,
                info="Ein Kanal ist ein eigener Zweig des Programms: Er enthält immer den Standard und dazu Zusätze, die nur bestimmte Häuser brauchen. Seine Versionen heißen z. B. 2.4.4-ahorn. Nach dem Eintragen zeigt „Update prüfen“ den Wechsel an, auch wenn die Versionsnummer gleich ist. Feld leeren und erneut aktualisieren stellt das Haus zurück auf den Standard, die Zusätze werden dabei entfernt. Ein Kanal wird nie auf eine ältere Version zurückgestellt."),
        Setting("pat_token", U, "Zugriffstoken", "Nur nötig, wenn das Repository privat ist (Leserecht auf Inhalte). Wird verschlüsselt gespeichert und nie angezeigt. Leer lassen = unverändert.", type="secret"),
    ), page="system"),
)


def section(section_id: str) -> Section:
    for s in SECTIONS:
        if s.id == section_id:
            return s
    raise KeyError(section_id)


def coerce(setting: Setting, value: Any) -> Any:
    """Wandelt einen Eingabewert in den gespeicherten Typ und prüft ihn.
    Wirft SettingError mit verständlicher Meldung."""
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
            raise SettingError(f"höchstens {setting.maximum}")
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
            raise SettingError("höchstens 500 Zeichen")
    if setting.check:
        setting.check(v)
    return v
