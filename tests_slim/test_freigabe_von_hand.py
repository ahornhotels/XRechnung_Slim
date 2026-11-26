"""Tests: eine haengende Rechnungsmail von Hand ohne XRechnung freigeben (nur PDF)
und der ungekuerzte Fehlertext des Validators."""
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from slim.api_slim import retry as retry_api
from slim.api_slim import status as status_api
from slim.jobs_slim import poller

HOTEL = {"suite8_recognize_subject_pattern": r"Rechnung #(?P<zinv_number>\d+)"}
RECHNUNG = {"wmai_id": 7, "filename": "Folio_568826.pdf", "subject": "Ihre Rechnung #568826",
            "to": "kunde@firma.example", "fideliodate": "2026-11-26"}
FEHLER = "zinv=568826: Validator-Fail: 1 Issues (Anzahlung nicht automatisch abbildbar)"


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(retry_api.router)
    status_api.get_state().update({"data_dir": tmp_path, "interval_seconds": 30,
                                   "last_run": None, "last_run_summary": None})
    return TestClient(app), tmp_path


def _aufruf(c, wmai_id, mail, fehler, frei=True):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock(name="conn"))
    cm.__exit__ = MagicMock(return_value=None)
    with patch.object(retry_api, "get_connection", return_value=cm), \
         patch.object(retry_api, "load_hotel_config", return_value=HOTEL), \
         patch.object(retry_api, "get_blocked_wmai", return_value=mail), \
         patch.object(retry_api, "get_wmai_error", return_value=fehler, create=True), \
         patch.object(retry_api, "release_wmai", return_value=frei) as rel:
        return c.post(f"/api/wmai/{wmai_id}/ohne-xrechnung"), rel


def _protokoll(dd):
    return [json.loads(z) for p in dd.glob("audit-*.jsonl")
            for z in p.read_text(encoding="utf-8").splitlines()]


def test_haengende_rechnungsmail_ohne_xrechnung_freigeben(client):
    c, dd = client
    r, rel = _aufruf(c, 7, RECHNUNG, FEHLER)
    assert r.status_code == 200 and r.json() == {"ok": True, "wmai_id": 7}
    rel.assert_called_once()
    e = [x for x in _protokoll(dd) if x["event"] == "freigegeben_ohne_xrechnung"]
    assert len(e) == 1 and e[0]["wmai_id"] == 7 and e[0]["zinv_number"] == "568826"
    d = e[0]["details"]
    assert d["von_hand"] is True and d["by"]
    assert d["letzter_fehler"] == FEHLER and d["hoteldatum"] == "2026-11-26"


def test_mail_ohne_fehler_wird_nicht_freigegeben(client):
    """Eine Mail ohne Fehlertext bekommt ihre XRechnung beim naechsten Durchlauf."""
    c, dd = client
    r, rel = _aufruf(c, 7, RECHNUNG, None)
    assert r.status_code == 409 and "nächsten Durchlauf" in r.json()["detail"]
    rel.assert_not_called()
    assert _protokoll(dd) == []


def test_fremde_mail_geht_nicht_ueber_diesen_weg(client):
    c, _ = client
    fremd = dict(RECHNUNG, filename="", subject="Ihre Reservierungsbestätigung 55012")
    r, rel = _aufruf(c, 7, fremd, FEHLER)
    assert r.status_code == 409 and "keine Rechnungsmail" in r.json()["detail"]
    rel.assert_not_called()


def test_nicht_mehr_gesperrte_mail_404(client):
    c, dd = client
    r, rel = _aufruf(c, 7, None, None)
    assert r.status_code == 404
    rel.assert_not_called()
    r, rel = _aufruf(c, 7, RECHNUNG, FEHLER, frei=False)     # zwischenzeitlich verschickt
    assert r.status_code == 404 and _protokoll(dd) == []


def test_freigabe_nur_fuer_verwalter():
    from slim.api_slim import auth_api
    assert auth_api._needs_admin("POST", "/api/wmai/7/ohne-xrechnung") is True


# ───────────────────────── Fehlertext des Validators ─────────────────────────

def test_validator_fehlertext_ungekuerzt_und_vollstaendig():
    lang = ("Anzahlung nicht automatisch abbildbar: nur Anzahlungsbuchungen ohne Leistung "
            "(Erstattung/Ausbuchung einer Anzahlung) - bitte manuell pruefen.")
    issues = [{"message": lang}] + [{"message": f"Feld {i} fehlt"} for i in range(1, 5)]
    text = poller.validator_fehlertext(issues)
    assert text.startswith("Validator-Fail: 5 Issues (")
    assert lang in text and "Feld 4 fehlt" in text
    assert poller._classify_failure(RuntimeError(text)) == "validator_fail"


def test_detailseite_bietet_freigabe_ohne_xrechnung():
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / "slim" / "frontend" / "rechnung.html").read_text(encoding="utf-8")
    assert "/ohne-xrechnung" in html and "Ohne XRechnung freigeben" in html
