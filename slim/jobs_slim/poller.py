"""
slim/jobs_slim/poller.py
------------------------
Slim-Variante des Suite8-WMAI-Anhang-Pollers.

Identische Geschäftslogik wie jobs/suite8_attach_poller.py, aber OHNE
SQLite-Queue und OHNE DB-Audit-Log. Stattdessen:

  - Erfolg     → archive_fs.save_xml + audit_jsonl 'attach_ok'
  - Misserfolg → set_wmai_error (Suite8-UI) + audit_jsonl-Eintrag
                 (mit Spam-Schutz, schreibt nur wenn sich der Fehlertext
                 geändert hat — gleiche Heuristik wie in der Big-App)

Wird vom APScheduler in slim/main_slim.py einmal pro
`suite8_poll_interval_seconds` aufgerufen.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.config_loader import load_hotel_config
from core.db_connector import get_connection
from modules import invoice_fetcher, invoice_validator, xml_builder, kosit_validator
from modules.kosit_validator import KositValidationError
from modules.suite8_mailer import (
    find_pending_wmai, attach_xml_to_wmai,
    set_wmai_error, get_wmai_error, WMAI_ERROR_MAX,
)
from modules.suite8_pattern import (
    extract_zinv_number, PatternMatchError, AmbiguousMatchError,
)

from slim.core_slim import audit_jsonl, archive_fs, overrides

logger = logging.getLogger(__name__)

# Per-Iteration Pending-Limit: KoSIT-Subprocess kostet ~2-4s, bei 50 über
# der APScheduler-Misfire-Grace-Time. Konservativ 10 — nächster Lauf
# (Default-Intervall 30s) holt den Rest.
_PENDING_LIMIT_PER_RUN = 10


def _audit_fail_with_spam_guard(
    data_dir: Path,
    event: str,
    wmai_id: int,
    zinv_number: Optional[str],
    error_text: str,
    conn,
) -> bool:
    """Schreibt Audit + WMAI_ERROR NUR wenn sich der Fehlertext geändert hat.

    Truncation-Limit identisch zu `set_wmai_error` (WMAI_ERROR_MAX=2000),
    damit der Vergleich konsistent ist und Spam-Guard auch bei langen
    Fehlern greift.

    Returns:
        True wenn DB-Cleanup erfolgreich, False wenn die Connection broken
        ist (Caller sollte dann den Loop abbrechen statt mit kaputter
        Connection weiterzuiterieren).
    """
    truncated = (error_text or "")[:WMAI_ERROR_MAX]
    try:
        previous = get_wmai_error(wmai_id, conn) or ""
    except Exception:
        logger.exception("WMAI_ERROR-Read fehlgeschlagen (wmai=%s) — Connection broken?", wmai_id)
        return False

    if truncated == previous:
        # Identischer Fehler — kein Audit, kein neues UPDATE
        # (Operator koennte parallel WMAI_ERROR=NULL gesetzt haben, das
        # wuerden wir sonst sofort wieder überschreiben).
        return True

    audit_jsonl.record_safe(
        data_dir, event,
        wmai_id=wmai_id, zinv_number=zinv_number,
        details={"error": truncated},
    )
    try:
        set_wmai_error(wmai_id, truncated, conn)
    except Exception:
        logger.exception("WMAI_ERROR-Update fehlgeschlagen (wmai=%s)", wmai_id)
        return False
    return True


def run_once(data_dir: Optional[Path] = None) -> dict:
    """Eine Polling-Runde.

    Args:
        data_dir: Pfad für JSONL-Audit und XML-Archive. Default:
                  <slim>/data — wird aufgerufen mit explizitem Wert
                  von main_slim.py um Test-Isolation zu erlauben.

    Returns:
        Statistik-Dict:
        {"attached": int, "failed": int, "no_match": int,
         "ambiguous": int, "skipped_strategy": bool}
    """
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir = Path(data_dir)

    cfg = load_hotel_config()
    # Slim laeuft nur für mail_strategy='suite8' — bei anderer Konfig
    # gibt es nichts zu tun (Big-App übernimmt).
    if (cfg.get("mail_strategy") or "suite8") not in ("suite8", "auto"):
        return {"skipped_strategy": True, "attached": 0, "failed": 0,
                "no_match": 0, "ambiguous": 0}

    fn_pat = cfg.get("suite8_recognize_filename_pattern", "")
    sub_pat = cfg.get("suite8_recognize_subject_pattern", "")
    fname_tmpl = cfg.get("suite8_attachment_name_template", "{zinv_number}.xml")

    summary = {"attached": 0, "failed": 0, "no_match": 0, "ambiguous": 0,
               "skipped_strategy": False}

    # Liste der Pending-WMAIs in eigener Connection holen — danach pro WMAI
    # eine frische Connection im inner-Loop. So koennen Connection-Breaks
    # einer einzelnen WMAI nicht alle nachfolgenden mitreissen, und der
    # bekannte Cursor-Lifecycle-Bug in attach_xml_to_wmai (kein
    # try/finally cur.close()) sammelt sich nicht über 50 Iterationen.
    try:
        with get_connection() as conn:
            pending = find_pending_wmai(conn=conn, limit=_PENDING_LIMIT_PER_RUN)
    except Exception as e:
        logger.exception("Konnte Pending-WMAIs nicht abfragen")
        audit_jsonl.record_safe(
            data_dir, "poller_db_error",
            details={"error": str(e)[:400], "phase": "find_pending"},
        )
        summary["db_error"] = True
        return summary

    for row in pending:
        wmai_id = row["wmai_id"]
        zinv_number: Optional[str] = None

        # Eigene Connection pro WMAI — wenn DB-Cleanup einer einzelnen
        # WMAI scheitert, fahren die nächsten mit einer frischen
        # Connection weiter.
        try:
            conn_ctx = get_connection()
        except Exception as e:
            logger.exception("get_connection fehlgeschlagen — Abbruch")
            audit_jsonl.record_safe(
                data_dir, "poller_db_error",
                details={"error": str(e)[:400], "phase": "per_wmai_conn",
                         "remaining": len(pending)},
            )
            summary["db_error"] = True
            break

        with conn_ctx as conn:
            # === Schritt 1: Pattern-Match ===
            try:
                kind, value = extract_zinv_number(
                    filename=row["filename"], subject=row["subject"],
                    filename_pattern=fn_pat, subject_pattern=sub_pat,
                )
            except AmbiguousMatchError as e:
                summary["ambiguous"] += 1
                _audit_fail_with_spam_guard(
                    data_dir, "pattern_ambiguous", wmai_id, None,
                    str(e), conn,
                )
                continue
            except PatternMatchError as e:
                summary["no_match"] += 1
                _audit_fail_with_spam_guard(
                    data_dir, "pattern_no_match", wmai_id, None,
                    f"filename={row['filename']!r} subject={row['subject']!r}: {e}",
                    conn,
                )
                continue

            # === Schritt 2: Fetch + Validate + Build + KoSIT + Attach ===
            try:
                if kind == "zinv_id":
                    zinv_id = int(value)
                    inv = invoice_fetcher.fetch_invoice(zinv_id)
                    if inv is None:
                        raise RuntimeError(
                            f"ZINV mit ID {zinv_id} nicht gefunden"
                        )
                    zinv_number = str(inv.get("header", {}).get("id") or zinv_id)
                else:  # kind == "zinv_number"
                    zinv_number = value
                    zinv_id = invoice_fetcher.find_zinv_id_by_number(zinv_number)
                    if not zinv_id:
                        raise RuntimeError(f"ZINV mit Nummer {zinv_number} nicht gefunden")
                    inv = invoice_fetcher.fetch_invoice(zinv_id)
                    if inv is None:
                        raise RuntimeError(
                            f"fetch_invoice lieferte None für zinv_id={zinv_id}"
                        )

                # Operator-Overrides für dieses WMAI anwenden (falls
                # vorhanden), BEVOR der Validator anschlaegt — ermöglicht
                # das gezielte Nachreichen fehlender Felder (z.B.
                # Kunden-E-Mail, BuyerReference) ohne dass Suite8
                # nachgepflegt werden muss.
                inv = overrides.apply_to_invoice(data_dir, wmai_id, inv)

                issues = invoice_validator.validate(inv)
                if issues:
                    msgs = "; ".join(i["message"][:80] for i in issues[:3])
                    raise RuntimeError(
                        f"Validator-Fail: {len(issues)} Issues ({msgs})"
                    )

                xml = xml_builder.build_and_validate(inv)

                # KoSIT-Pflicht-Gate (per Spec). Bei fehlender JAR/JRE wirft
                # validate FileNotFoundError, bei BR-Verletzung
                # KositValidationError — beides Fail-Branches, die als
                # 'kosit_fail' geauditet werden.
                try:
                    kosit_validator.validate(xml)
                except FileNotFoundError as e:
                    raise RuntimeError(f"KoSIT nicht verfügbar: {e}")

                # Dateiname aus dem Template — gilt einheitlich fuer den
                # Suite8-Anhang UND die Archivdatei auf der Platte.
                filename = fname_tmpl.format(zinv_number=zinv_number)

                # Archiv schreiben BEVOR wir attachen — wenn der Filesystem-
                # Schreibvorgang fehlschlaegt, hat Suite8 noch keinen
                # Anhang, ein Retry passt also.
                arch = archive_fs.save_xml(
                    data_dir, zinv_number, xml, filename=filename,
                )

                # Anhängen (atomar in der Suite8-DB).
                result = attach_xml_to_wmai(
                    wmai_id=wmai_id, xml_bytes=xml,
                    filename=filename, conn=conn,
                )
                summary["attached"] += 1
                # Override-Datei nach erfolgreichem Attach löschen — sie
                # hat ihren Zweck erfüllt, und sollte nicht versehentlich
                # bei einer Folge-WMAI mit gleicher ID nochmal angewandt werden.
                had_override = overrides.delete(data_dir, wmai_id)
                audit_jsonl.record_safe(
                    data_dir, "attach_ok",
                    wmai_id=wmai_id, zinv_number=zinv_number,
                    details={
                        "wmaa_id": result["wmaa_id"],
                        "wtxt_id": result["wtxt_id"],
                        "sha256": arch["sha256"],
                        "xml_path": arch["xml_path"],
                        **({"override_consumed": True} if had_override else {}),
                    },
                )

            except Exception as e:
                summary["failed"] += 1
                event = _classify_failure(e)
                logger.exception(
                    "Suite8-Attach fehlgeschlagen (wmai=%s zinv=%s)",
                    wmai_id, zinv_number,
                )
                _audit_fail_with_spam_guard(
                    data_dir, event, wmai_id, zinv_number,
                    f"zinv={zinv_number}: {e}",
                    conn,
                )

    return summary


def _classify_failure(e: Exception) -> str:
    """Mappt eine Exception auf einen Audit-Event-Namen.

    KoSIT-Fehler bekommen einen eigenen Event-Code, damit das Audit
    klar zwischen Validator-Fail (eigener Pflichtfeld-Check) und
    KoSIT-Fail (XRechnung-Spec-Check) unterscheidet.
    """
    if isinstance(e, KositValidationError):
        return "kosit_fail"
    if isinstance(e, xml_builder.XmlBuildError):
        return "xml_build_fail"
    msg = str(e)
    if "KoSIT nicht verfügbar" in msg:
        return "kosit_fail"
    if msg.startswith("Validator-Fail"):
        return "validator_fail"
    if "nicht gefunden" in msg and "ZINV" in msg:
        return "zinv_not_found"
    return "attach_fail"
