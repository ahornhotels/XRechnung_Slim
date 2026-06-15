"""
slim/api_slim/config_api.py
---------------------------
Schreibzugriff auf den Pattern-Block in slim/config/hotel.json.

Jedes Hotel hat einen eigenen Suite8-Mail-Template — die Regex
muss pro Installation konfigurierbar sein. Im UI editierbar, hier
serverseitig validiert (compile-check, Named-Group-Pflicht,
Length-Cap gegen Regex-DoS).

Pattern-Tester (POST /api/config/pattern/test) ermöglicht es,
ein Pattern gegen einen Beispiel-Filename/Subject zu prüfen
bevor man speichert.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from core.config_loader import CONFIG_DIR, load_json, save_json
from modules.suite8_pattern import (
    extract_zinv_number, validate_pattern as _validate_pattern_re,
    generate_combined_pattern_from_numbers,
    PatternMatchError, AmbiguousMatchError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])


# Pattern-Length-Cap gegen ReDoS-Eingaben (Operator-only, aber sicher ist sicher).
_PATTERN_MAX_LEN = 500


def _validate_pattern(pattern: str, field_name: str) -> None:
    """Prüfung beim Save.

    - Laenge unter dem Cap?
    - compilable + genau EINE der Named-Groups (zinv_id ODER zinv_number)?

    Leere Strings sind erlaubt (= "Pattern nicht aktiv").
    Wirft HTTPException(400) bei Verstoss.
    """
    if not pattern:
        return
    if len(pattern) > _PATTERN_MAX_LEN:
        raise HTTPException(
            400,
            detail=f"{field_name}: maximal {_PATTERN_MAX_LEN} Zeichen "
                   f"(eingegeben: {len(pattern)})",
        )
    try:
        _validate_pattern_re(pattern)
    except PatternMatchError as e:
        raise HTTPException(400, detail=f"{field_name}: {e}")


class PatternPayload(BaseModel):
    """Eingabe für GET-/POST-/Test-Endpoints."""
    suite8_recognize_filename_pattern: str = Field(default="", max_length=_PATTERN_MAX_LEN)
    suite8_recognize_subject_pattern: str = Field(default="", max_length=_PATTERN_MAX_LEN)
    suite8_attachment_name_template: str = Field(
        default="{zinv_number}.xml", max_length=128,
    )

    @field_validator("suite8_attachment_name_template")
    @classmethod
    def _name_must_contain_zinv(cls, v: str) -> str:
        if "{zinv_number}" not in v:
            raise ValueError(
                "Template braucht den Platzhalter {zinv_number}"
            )
        return v


class PatternTestPayload(BaseModel):
    filename_pattern: str = Field(default="", max_length=_PATTERN_MAX_LEN)
    subject_pattern: str = Field(default="", max_length=_PATTERN_MAX_LEN)
    filename: str = Field(default="", max_length=2000)
    subject: str = Field(default="", max_length=2000)


class PatternGenerateExample(BaseModel):
    """Ein Beispiel-Betreff plus die vom Operator getippte Rechnungsnummer."""
    example: str = Field(..., min_length=1, max_length=2000)
    number: str = Field(..., min_length=1, max_length=64)


class PatternGeneratePayload(BaseModel):
    """Eingabe für /pattern/generate.

    Der Operator gibt 1..n Beispiel-Betreffe ein (z.B. deutsch + englisch)
    und tippt zu jedem die echte Rechnungsnummer. Daraus wird EIN
    kombiniertes Regex gebaut (Alternation über die Anker)."""
    examples: list[PatternGenerateExample] = Field(..., min_length=1, max_length=5)
    kind: str = Field(default="zinv_number",
                      pattern="^(zinv_number|zinv_id)$")


def _read_pattern() -> PatternPayload:
    cfg = load_json(CONFIG_DIR / "hotel.json", default={}) or {}
    return PatternPayload(
        suite8_recognize_filename_pattern=cfg.get(
            "suite8_recognize_filename_pattern", ""
        ),
        suite8_recognize_subject_pattern=cfg.get(
            "suite8_recognize_subject_pattern", ""
        ),
        suite8_attachment_name_template=cfg.get(
            "suite8_attachment_name_template", "{zinv_number}.xml"
        ),
    )


@router.get("/pattern")
def get_pattern() -> PatternPayload:
    """Liefert die aktuelle Pattern-Konfig (aus hotel.json)."""
    return _read_pattern()


@router.post("/pattern")
def post_pattern(payload: PatternPayload) -> PatternPayload:
    """Speichert die neue Pattern-Konfig in hotel.json.

    Validierung:
    - Beide Patterns müssen compilable sein und die Named-Group enthalten
      (oder leer)
    - Mindestens ein Pattern muss gesetzt sein, sonst koennte der Poller
      nichts matchen
    """
    _validate_pattern(
        payload.suite8_recognize_filename_pattern, "filename_pattern"
    )
    _validate_pattern(
        payload.suite8_recognize_subject_pattern, "subject_pattern"
    )
    if not payload.suite8_recognize_filename_pattern \
            and not payload.suite8_recognize_subject_pattern:
        raise HTTPException(
            400,
            detail="Mindestens eines der Patterns (filename/subject) "
                   "muss gesetzt sein — sonst kann der Poller keine "
                   "Rechnungsnummer extrahieren.",
        )

    cfg_path = CONFIG_DIR / "hotel.json"
    cfg = load_json(cfg_path, default=None)
    if cfg is None:
        raise HTTPException(
            503,
            detail="hotel.json nicht vorhanden — bitte zuerst aus "
                   "hotel.json.example anlegen.",
        )
    cfg["suite8_recognize_filename_pattern"] = \
        payload.suite8_recognize_filename_pattern
    cfg["suite8_recognize_subject_pattern"] = \
        payload.suite8_recognize_subject_pattern
    cfg["suite8_attachment_name_template"] = \
        payload.suite8_attachment_name_template
    save_json(cfg_path, cfg)
    logger.info(
        "Pattern-Konfig aktualisiert: filename=%r subject=%r template=%r",
        payload.suite8_recognize_filename_pattern,
        payload.suite8_recognize_subject_pattern,
        payload.suite8_attachment_name_template,
    )
    return payload


@router.post("/pattern/generate")
def pattern_generate(payload: PatternGeneratePayload) -> dict:
    """Erzeugt EIN kombiniertes Regex-Pattern aus 1..n Beispiel-Betreffen.

    Operatoren müssen kein Regex schreiben: sie geben echte Betreffe aus
    Suite8 ein (z.B. deutsch + englisch) und tippen zu jedem die echte
    Rechnungsnummer. Die App ankert datums-robust auf den Text vor der
    Nummer und verschmilzt mehrere Sprachen zu einer Alternation.
    """
    examples = [{"text": e.example, "number": e.number} for e in payload.examples]
    return generate_combined_pattern_from_numbers(
        examples, group_name=payload.kind,
    )


@router.post("/pattern/test")
def test_pattern(payload: PatternTestPayload) -> dict:
    """Dry-Run: probiert die aktuell eingegebenen Patterns gegen ein
    Beispiel-Filename/Subject und meldet zurueck, was extrahiert worden
    waere — oder warum nicht.

    Speichert NICHTS. Pure-Function-Test für das UI.
    """
    # Validierung BEIDER Patterns vorab (klare Fehler bei Syntax-Bugs).
    _validate_pattern(payload.filename_pattern, "filename_pattern")
    _validate_pattern(payload.subject_pattern, "subject_pattern")

    if not payload.filename_pattern and not payload.subject_pattern:
        return {
            "matched": False,
            "result": None,
            "source": None,
            "error": "Kein Pattern angegeben.",
        }

    try:
        kind, value = extract_zinv_number(
            filename=payload.filename or "",
            subject=payload.subject or "",
            filename_pattern=payload.filename_pattern,
            subject_pattern=payload.subject_pattern,
        )
    except AmbiguousMatchError as e:
        return {"matched": False, "result": None, "kind": None,
                "source": "both", "error": f"Ambiguous: {e}"}
    except PatternMatchError as e:
        return {"matched": False, "result": None, "kind": None,
                "source": None, "error": f"Kein Match: {e}"}

    # Welche Seite hat getroffen? Mit der konkreten Group-Art prüfen.
    source = None
    for src, txt, pat in (
        ("filename", payload.filename or "", payload.filename_pattern),
        ("subject", payload.subject or "", payload.subject_pattern),
    ):
        if not pat:
            continue
        try:
            m = re.search(pat, txt, flags=re.IGNORECASE)
        except re.error:
            continue
        if m and kind in m.groupdict() and m.group(kind) == value:
            source = src
            break

    return {
        "matched": True,
        "result": value,
        "kind": kind,
        "source": source,
        "error": None,
    }
