"""
slim/api_slim/run_now.py
------------------------
Manueller Force-Poll-Endpunkt mit detailliertem Trace.

Wird vom UI ausgeloest ("Jetzt einmal pollen") und gibt pro WMAI eine
Schritt-fuer-Schritt-Aufschluesselung zurueck:
  - mail_strategy-Check
  - Pattern-Match (mit konkreten Werten)
  - Fetch + Validate + KoSIT + Attach

So sieht der Operator SOFORT wo der Poller aussteigt, ohne in
JSONL-Audit oder Service-Logs schauen zu muessen.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from core.config_loader import load_hotel_config
from core.db_connector import get_connection
from modules import invoice_fetcher, invoice_validator, xml_builder, kosit_validator
from modules.kosit_validator import KositValidationError
from modules.suite8_mailer import find_pending_wmai, get_wmai_error
from modules.suite8_pattern import (
    extract_zinv_number, PatternMatchError, AmbiguousMatchError,
)

from slim.api_slim.status import get_state
from slim.core_slim import overrides
from slim.core_slim.clock import now_local

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/poller", tags=["poller"])


def _step(events: list, ok: bool, name: str, detail: str = ""):
    events.append({"step": name, "ok": ok, "detail": detail})


@router.post("/run-now")
def run_now(state: dict = Depends(get_state)):
    """Force-Poll mit Trace. Macht ALLE Schritte ausser dem eigentlichen
    Attach (nur dry-run bis vor Attach) — damit produktive WMAIs nicht
    versehentlich abgearbeitet werden.

    Wer 'echt' pollen will: ueber den /api/wmai/{id}/retry-Endpoint plus
    naechsten regulaeren Poll-Lauf.
    """
    started = time.monotonic()
    data_dir = Path(state.get("data_dir") or ".")

    result = {
        "started_at": now_local().isoformat(),
        "config": {},
        "wmais": [],
        "summary": {"total": 0, "match": 0, "no_match": 0,
                    "ambiguous": 0, "validator_fail": 0, "kosit_fail": 0,
                    "ready_to_attach": 0},
    }

    # ── Config laden + Strategie pruefen ──
    try:
        cfg = load_hotel_config()
    except FileNotFoundError as e:
        raise HTTPException(503, f"hotel.json fehlt: {e}")

    fn_pat = cfg.get("suite8_recognize_filename_pattern", "") or ""
    sub_pat = cfg.get("suite8_recognize_subject_pattern", "") or ""
    mail_strategy = cfg.get("mail_strategy")

    result["config"] = {
        "mail_strategy": mail_strategy,
        "subject_pattern": sub_pat,
        "filename_pattern": fn_pat,
    }

    if mail_strategy not in ("suite8", "auto"):
        result["abort_reason"] = (
            f"mail_strategy={mail_strategy!r} - Poller wuerde im Regular-Run "
            f"skipped. In hotel.json auf 'suite8' setzen und Service neu starten."
        )
        return result

    if not fn_pat and not sub_pat:
        result["abort_reason"] = (
            "Kein Pattern konfiguriert. Wizard-Schritt 5 nochmal durchklicken "
            "oder im Status-UI unter 'Pattern-Konfiguration' Pattern erzeugen."
        )
        return result

    # ── Pending WMAIs lesen ──
    try:
        with get_connection() as conn:
            pending = find_pending_wmai(conn=conn, limit=20)
    except Exception as e:
        raise HTTPException(503, f"DB-Connect: {e}")

    result["summary"]["total"] = len(pending)

    if not pending:
        result["abort_reason"] = (
            "Keine WMAI mit BLOCKSEND=1 und SENT=0 in V8LIVE - der Trigger "
            "feuert vermutlich nicht. Trigger-SQL pruefen und neu deployen, "
            "ODER fuer Test eine WMAI manuell auf BLOCKSEND=1 setzen."
        )
        return result

    # ── Pro WMAI durch die ganze Pipeline (DRY-RUN, kein Attach) ──
    for row in pending:
        wmai_id = row["wmai_id"]
        wmai_trace = {
            "wmai_id": wmai_id,
            "filename": row["filename"][:120] if row["filename"] else "",
            "subject": row["subject"][:120] if row["subject"] else "",
            "events": [],
            "outcome": "?",
        }
        events = wmai_trace["events"]

        # Pattern-Match
        try:
            kind, value = extract_zinv_number(
                filename=row["filename"], subject=row["subject"],
                filename_pattern=fn_pat, subject_pattern=sub_pat,
            )
            _step(events, True, "pattern_match", f"{kind}={value}")
        except AmbiguousMatchError as e:
            _step(events, False, "pattern_match", f"AMBIGUOUS: {e}")
            wmai_trace["outcome"] = "ambiguous"
            result["summary"]["ambiguous"] += 1
            result["wmais"].append(wmai_trace)
            continue
        except PatternMatchError as e:
            _step(events, False, "pattern_match", f"no match: {e}")
            wmai_trace["outcome"] = "no_match"
            result["summary"]["no_match"] += 1
            result["wmais"].append(wmai_trace)
            continue

        result["summary"]["match"] += 1

        # Fetch
        try:
            if kind == "zinv_id":
                zinv_id = int(value)
                inv = invoice_fetcher.fetch_invoice(zinv_id)
                if inv is None:
                    raise RuntimeError(f"ZINV mit ID {zinv_id} nicht gefunden")
            else:
                zinv_id = invoice_fetcher.find_zinv_id_by_number(value)
                if not zinv_id:
                    raise RuntimeError(f"ZINV-Nummer {value} nicht gefunden")
                inv = invoice_fetcher.fetch_invoice(zinv_id)
            zinv_number = str(inv.get("header", {}).get("id") or value)
            _step(events, True, "fetch_invoice",
                  f"zinv_id={zinv_id}, lines={len(inv.get('lines', []))}")
        except Exception as e:
            _step(events, False, "fetch_invoice", str(e))
            wmai_trace["outcome"] = "fetch_fail"
            result["wmais"].append(wmai_trace)
            continue

        # Override anwenden
        inv = overrides.apply_to_invoice(data_dir, wmai_id, inv)

        # Validator
        issues = invoice_validator.validate(inv)
        if issues:
            msgs = "; ".join(i["message"][:60] for i in issues[:3])
            _step(events, False, "validator", f"{len(issues)} Issues: {msgs}")
            wmai_trace["outcome"] = "validator_fail"
            result["summary"]["validator_fail"] += 1
            result["wmais"].append(wmai_trace)
            continue
        _step(events, True, "validator", "0 Issues")

        # XML-Build
        try:
            xml = xml_builder.build_and_validate(inv)
            _step(events, True, "xml_build", f"{len(xml)} Bytes")
        except Exception as e:
            _step(events, False, "xml_build", str(e)[:200])
            wmai_trace["outcome"] = "xml_build_fail"
            result["wmais"].append(wmai_trace)
            continue

        # KoSIT
        try:
            kosit_validator.validate(xml)
            _step(events, True, "kosit", "OK")
        except FileNotFoundError as e:
            _step(events, False, "kosit", f"KoSIT nicht verfuegbar: {e}")
            wmai_trace["outcome"] = "kosit_unavailable"
            result["wmais"].append(wmai_trace)
            continue
        except KositValidationError as e:
            err = e.errors[0][:200] if e.errors else "(kein Detail)"
            _step(events, False, "kosit", err)
            wmai_trace["outcome"] = "kosit_fail"
            result["summary"]["kosit_fail"] += 1
            result["wmais"].append(wmai_trace)
            continue

        _step(events, True, "ready_to_attach",
              f"zinv_number={zinv_number}, xml ready")
        wmai_trace["outcome"] = "ready_to_attach"
        wmai_trace["zinv_number"] = zinv_number
        result["summary"]["ready_to_attach"] += 1
        result["wmais"].append(wmai_trace)

    result["elapsed_seconds"] = round(time.monotonic() - started, 2)
    return result
