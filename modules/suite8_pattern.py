"""
modules/suite8_pattern.py
-------------------------
Pure-Function: extrahiert eine Rechnungs-Identifikation aus WMAI-Subject
und/oder WMAI_ATTACHMENT_FILE_NAME basierend auf konfigurierten Regex-
Patterns. Keine DB-Abhaengigkeit, einfach testbar.

Pattern-Konvention:
    Eine Named-Group, entweder ``(?P<zinv_id>\\d+)`` ODER
    ``(?P<zinv_number>\\d+)``.

Hintergrund: Suite8 schreibt im PDF-Filename die ``ZINV_ID`` (interner
DB-Primaerschluessel), im Subject (sofern der Mail-Template das traegt)
die ``ZINV_NUMBER`` (die externe Rechnungs-Folio-Nummer, die der Kunde
sieht). Die Identifikation muss klar markiert sein, damit der Poller
weiss, ob er direkt ``fetch_invoice(zinv_id)`` oder
``find_zinv_id_by_number(zinv_number)`` aufrufen muss — die Bedeutung
der Zahl unterscheidet sich essenziell.

Return-Type: ``tuple[Literal["zinv_id", "zinv_number"], str]``.
"""
import re
from typing import Literal, Optional, Tuple


PatternKind = Literal["zinv_id", "zinv_number"]
PATTERN_GROUPS: tuple[PatternKind, PatternKind] = ("zinv_id", "zinv_number")


class PatternMatchError(Exception):
    """Pattern hat nichts getroffen oder ist syntaktisch kaputt."""


class AmbiguousMatchError(Exception):
    """Filename- und Subject-Pattern liefern unterschiedliche Werte
    (entweder andere Zahl oder andere Group-Art)."""


def _try_match(text: str, pattern: str) -> Optional[Tuple[PatternKind, str]]:
    """Liefert ``(kind, value)`` oder None.

    Pruefung beider Named-Groups ``zinv_id`` und ``zinv_number``;
    genau eine davon muss im Pattern vorkommen. Bei Verstoss
    PatternMatchError.
    """
    if not pattern or not text:
        return None
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise PatternMatchError(f"Regex ungueltig: {e}") from e

    present = [g for g in PATTERN_GROUPS if g in rx.groupindex]
    if not present:
        raise PatternMatchError(
            "Pattern braucht eine Named-Group (?P<zinv_id>\\d+) "
            "oder (?P<zinv_number>\\d+)"
        )
    if len(present) > 1:
        raise PatternMatchError(
            "Pattern darf nur EINE der Named-Groups (zinv_id / zinv_number) "
            "enthalten — sonst ist unklar, ob es eine ID oder eine Nummer ist."
        )
    kind = present[0]
    m = rx.search(text)
    if not m:
        return None
    return kind, m.group(kind)


def extract_zinv_number(
    *,
    filename: str,
    subject: str,
    filename_pattern: str,
    subject_pattern: str,
) -> Tuple[PatternKind, str]:
    """Extrahiert die Rechnungs-Identifikation aus Filename und/oder Subject.

    Beide Patterns werden geprueft. Wenn beide treffen mit identischem
    (kind, value), wird das Ergebnis zurueckgegeben. Bei Unterschied:
    AmbiguousMatchError.

    Returns:
        Tuple ``(kind, value)`` mit
        ``kind ∈ {"zinv_id", "zinv_number"}`` und ``value`` als String.

    Raises:
        PatternMatchError: kein Pattern konfiguriert, syntaktisch
            kaputt, fehlende/doppelte Named-Group, oder kein Treffer.
        AmbiguousMatchError: beide Patterns treffen, aber liefern
            unterschiedliche Werte oder unterschiedliche Group-Art.
    """
    if not filename_pattern and not subject_pattern:
        raise PatternMatchError("Kein Pattern konfiguriert")

    from_fn = _try_match(filename, filename_pattern)
    from_sub = _try_match(subject, subject_pattern)

    if from_fn and from_sub and from_fn != from_sub:
        raise AmbiguousMatchError(
            f"Filename liefert {from_fn!r}, Subject liefert {from_sub!r}"
        )
    result = from_fn or from_sub
    if result is None:
        raise PatternMatchError(
            f"Kein Pattern hat getroffen "
            f"(filename={filename!r}, subject={subject!r})"
        )
    return result


def generate_pattern_from_example(
    text: str,
    *,
    group_name: PatternKind = "zinv_number",
    anchor_words: int = 3,
) -> dict:
    """Generiert ein Regex-Pattern aus einem Beispiel-Text.

    Heuristik:
      1. Finde die LAENGSTE Zahl mit >= 3 Ziffern im Text. Das ist
         (annaehernd zuverlaessig) die Rechnungs-Nummer / -ID.
      2. Nimm die letzten ``anchor_words`` (Default 3) Woerter VOR
         dieser Zahl als woertlichen Anchor — re.escape'd und mit
         ``\\s+`` als Separator.
      3. Baue ``<anchor>\\s*(?P<group_name>\\d+)``.
      4. Verifiziere: matched das generierte Pattern den Beispiel-Text
         und liefert es dieselbe Zahl?

    Args:
        text: das Beispiel-Subject (oder Filename)
        group_name: 'zinv_number' (Default — fuer Subject-Patterns) oder
            'zinv_id' (fuer Filename-Patterns die Suite8-interne IDs tragen)
        anchor_words: wie viele Woerter VOR der Zahl als wortwoertlicher
            Match — mehr = spezifischer, weniger = robuster gegen Wording-
            Varianten. Bei 0 entsteht ein Pattern ohne Anchor (anfaellig
            fuer Falsch-Treffer wenn die Mail mehrere Zahlen enthaelt).

    Returns:
        Dict mit Schluesseln:
            ``ok``    (bool)
            ``pattern`` (str) - das generierte Regex (nur bei ok=True)
            ``matched`` (str) - die als Rechnungs-Nummer erkannte Zahl
            ``warning`` (str|None) - Hinweis bei schwacher Heuristik
            ``error`` (str) - Fehlerbeschreibung (nur bei ok=False)
    """
    if not text or not text.strip():
        return {"ok": False, "error": "Leeres Beispiel."}

    # Mindestens 3-stellig — verhindert Match auf Hausnummern, Postleitzahlen,
    # Jahres-Praefixe etc. die im Subject auftauchen koennen.
    candidates = list(re.finditer(r"\d{3,}", text))
    if not candidates:
        return {
            "ok": False,
            "error": "Keine Zahl mit mindestens 3 Ziffern im Beispiel gefunden. "
                     "Bitte ein Beispiel mit echter Rechnungsnummer eingeben.",
        }

    # Bei mehreren Kandidaten die laengste — Rechnungsnummern sind in der
    # Praxis 4-7 Stellen, Jahreszahlen 4. Bei Gleichstand: die LETZTE
    # nehmen (oft im Subject hinten: "Aufenthalt 2026 - Rechnung 12345").
    longest = sorted(
        candidates,
        key=lambda m: (len(m.group()), m.start()),
        reverse=True,
    )[0]
    zinv = longest.group()
    start = longest.start()

    # 1-3 Woerter davor sammeln. Wort = nicht-Whitespace-Sequenz.
    before = text[:start].rstrip()
    words = re.findall(r"\S+", before)
    anchor = words[-max(1, anchor_words):] if words else []

    warning = None
    if not anchor:
        # Zahl steht am Anfang - kein Anchor moeglich. Pattern wird sehr
        # generisch, der User wird gewarnt.
        pattern = rf"(?P<{group_name}>\d+)"
        warning = (
            "Im Beispiel steht keine Vortext-Info vor der Nummer — das "
            "erzeugte Pattern matcht JEDE Zahlenfolge in WMAI-Subjects. "
            "Bei mehrdeutigen Mails (z.B. mit Aufenthalts-Jahreszahl) "
            "manuell um einen Anchor erweitern."
        )
    else:
        escaped = [re.escape(w) for w in anchor]
        anchor_re = r"\s+".join(escaped)
        pattern = rf"{anchor_re}\s*(?P<{group_name}>\d+)"

    # Sanity-Check: matched es wirklich (case-insensitive, wie der Poller)?
    try:
        m = re.search(pattern, text, flags=re.IGNORECASE)
    except re.error as e:
        return {"ok": False, "error": f"Generiertes Pattern nicht compilebar: {e}"}
    if not m or m.group(group_name) != zinv:
        return {
            "ok": False,
            "error": "Generiertes Pattern matcht das Beispiel nicht — "
                     "bitte manuell anpassen.",
        }

    return {
        "ok": True,
        "pattern": pattern,
        "matched": zinv,
        "kind": group_name,
        "warning": warning,
    }


class _AnchorError(Exception):
    """Interner Fehler beim Anker-Bau aus einer getippten Nummer."""


def _anchor_from_number(text: str, number: str, anchor_words: int) -> Tuple[str, Optional[str]]:
    """Findet ``number`` als EIGENSTAENDIGE Zahl in ``text`` und baut den
    woertlichen Anker aus bis zu ``anchor_words`` Woertern davor.

    „Eigenstaendig" heisst: nicht innerhalb einer laengeren Ziffernfolge
    (verhindert, dass z.B. ``1448`` in ``144853`` trifft).

    Returns:
        ``(anchor_regex, warning)`` — ``anchor_regex`` ist die mit ``\\s+``
        verbundene, ``re.escape``'te Wortfolge VOR der Nummer (ohne die
        Nummer-Group selbst). ``warning`` ist gesetzt, wenn die Nummer
        mehrfach vorkommt.

    Raises:
        _AnchorError: Nummer nicht eigenstaendig im Text, oder kein
            Anker-Wort davor (Nummer steht am Anfang).
    """
    matches = list(re.finditer(rf"(?<!\d){re.escape(number)}(?!\d)", text))
    if not matches:
        raise _AnchorError(
            f"Die Zahl {number} steht nicht als eigenständige Zahl im Betreff "
            f"'{text}'. Bitte die vollständige Rechnungsnummer eingeben."
        )
    warning = None
    if len(matches) >= 2:
        warning = (
            f"Die Zahl {number} kommt im Betreff '{text}' mehrfach vor — Anker "
            f"auf das erste Vorkommen gesetzt; bitte das Ergebnis testen."
        )
    start = matches[0].start()
    before = text[:start].rstrip()
    words = re.findall(r"\S+", before)
    if not words:
        raise _AnchorError(
            f"Im Betreff '{text}' steht kein Text vor der Nummer {number} — so "
            f"lässt sich kein eindeutiger Anker bauen. Bitte einen Betreff mit "
            f"Vortext verwenden (z.B. 'Ihre Rechnung Nr. {number}')."
        )
    anchor = words[-max(1, anchor_words):]
    # Fuehrende reine Satzzeichen-Tokens (z.B. "-" in "... - Invoice number")
    # entfernen — sie machen den Anker bruechig, ohne ihn praeziser zu machen.
    # Satzzeichen MITTENDRIN bleiben erhalten (sonst zerbricht die Kontiguitaet).
    while anchor and not re.search(r"\w", anchor[0]):
        anchor = anchor[1:]
    if not anchor:
        raise _AnchorError(
            f"Im Betreff '{text}' steht vor der Nummer {number} nur Satzzeichen "
            f"— so lässt sich kein eindeutiger Anker bauen. Bitte einen Betreff "
            f"mit Vortext verwenden (z.B. 'Ihre Rechnung Nr. {number}')."
        )
    anchor_re = r"\s+".join(re.escape(w) for w in anchor)
    return anchor_re, warning


def generate_combined_pattern_from_numbers(
    examples,
    *,
    group_name: PatternKind = "zinv_number",
    anchor_words: int = 3,
) -> dict:
    """Baut aus 1..n ``{text, number}``-Beispielen EIN kombiniertes Regex.

    Der Operator tippt zu jedem Beispiel-Betreff die echte Rechnungsnummer.
    Pro Beispiel wird der Anker-Text vor der Nummer ermittelt; mehrere
    Anker werden zu einer Alternation ``(?:A|B)`` verschmolzen, gefolgt von
    EINER Named-Group. Beispiel (deutsch + englisch):

        ``(?:Ihre\\s+Rechnung\\s+Nr\\.|Invoice\\s+number)\\s*(?P<zinv_number>\\d+)``

    Im Gegensatz zur alten „laengste Zahl"-Heuristik ist das datums-robust:
    die getippte Nummer bestimmt den Anker, nicht eine Ratefunktion.

    Args:
        examples: Liste von Dicts mit ``text`` (Beispiel-Betreff) und
            ``number`` (die vom Operator getippte Rechnungsnummer).
        group_name: ``zinv_number`` (Subject, Default) oder ``zinv_id``.
        anchor_words: max. Anzahl Woerter vor der Nummer als Anker.

    Returns:
        Dict mit ``ok``; bei Erfolg ``pattern``, ``matched`` (Liste der
        Nummern), ``kind``, ``warning``; bei Fehler ``error``.
    """
    if not examples:
        return {"ok": False, "error": "Keine Beispiele angegeben."}

    anchors: list[str] = []
    numbers: list[str] = []
    texts: list[str] = []
    warnings: list[str] = []

    for ex in examples:
        text = (ex.get("text") or "").strip()
        number = (ex.get("number") or "").strip()
        if not text:
            return {"ok": False, "error": "Ein Beispiel-Betreff ist leer."}
        if not number:
            return {"ok": False,
                    "error": "Bitte zu jedem Betreff die Rechnungsnummer eintippen."}
        if not number.isdigit():
            return {"ok": False,
                    "error": f"'{number}' ist keine reine Zahl. Bitte nur die "
                             f"Ziffern der Rechnungsnummer eingeben."}
        try:
            anchor, warning = _anchor_from_number(text, number, anchor_words)
        except _AnchorError as e:
            return {"ok": False, "error": str(e)}
        anchors.append(anchor)
        numbers.append(number)
        texts.append(text)
        if warning:
            warnings.append(warning)

    # Gleiche Anker zusammenfassen (Reihenfolge erhalten), damit keine
    # sinnlose (?:a|a)-Alternation entsteht.
    unique = list(dict.fromkeys(anchors))
    anchor_part = unique[0] if len(unique) == 1 else "(?:" + "|".join(unique) + ")"
    pattern = rf"{anchor_part}\s*(?P<{group_name}>\d+)"

    # Verifizieren: das erzeugte Muster muss in JEDEM Beispiel exakt die
    # getippte Nummer liefern — sonst kein halbes Pattern speichern.
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return {"ok": False, "error": f"Generiertes Pattern nicht compilebar: {e}"}
    for text, number in zip(texts, numbers):
        m = rx.search(text)
        if not m or m.group(group_name) != number:
            return {
                "ok": False,
                "error": f"Das erzeugte Muster trifft im Betreff '{text}' nicht "
                         f"die Nummer {number} — bitte die Eingaben prüfen.",
            }

    return {
        "ok": True,
        "pattern": pattern,
        "matched": numbers,
        "kind": group_name,
        "warning": " ".join(warnings) if warnings else None,
    }


def validate_pattern(pattern: str) -> Optional[PatternKind]:
    """Server-Side-Helfer fuer Setup-Wizard und Config-UI.

    Validiert, dass das Pattern compilebar ist und GENAU eine der
    erlaubten Named-Groups enthaelt. Leerer String ist erlaubt
    (= Pattern nicht aktiv).

    Returns:
        Den Group-Namen wenn alles ok, None wenn Pattern leer ist.

    Raises:
        PatternMatchError: bei jedem Verstoss (Caller soll daraus eine
            HTTP-400-Antwort bauen).
    """
    if not pattern:
        return None
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise PatternMatchError(f"Regex nicht compilebar — {e}")
    present = [g for g in PATTERN_GROUPS if g in rx.groupindex]
    if not present:
        raise PatternMatchError(
            "Pattern braucht eine Named-Group "
            "(?P<zinv_id>\\d+) oder (?P<zinv_number>\\d+)"
        )
    if len(present) > 1:
        raise PatternMatchError(
            "Pattern darf nur EINE Named-Group enthalten "
            "(zinv_id ODER zinv_number)"
        )
    return present[0]
