"""
slim/api_slim/sql_view.py
-------------------------
Read-only-Endpunkte fuer Techniker / DBA: zeigen die SQL-Templates, die
der Poller intern verwendet, und das Original-Views-Dokument als
Referenz.

Keine DB-Schreibvorgaenge. Kein Auth (Slim-Konvention: bind 127.0.0.1).

Endpunkte:
  GET /api/sql/templates        - Liste aller invoice_*.sql Templates
  GET /api/sql/templates/{name} - einzelnes SQL-File als text/plain
  GET /api/sql/views-source     - docs/VIEWS_Customized_final.txt
                                  (Original-Views vor Inline-Expansion)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from slim.core_slim import sql_overrides
from slim.api_slim.status import get_state

router = APIRouter(prefix="/api/sql", tags=["sql"])

# Pfade ueber den Repo-Root bestimmen (slim/ liegt eine Ebene tiefer)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SQL_DIR = _REPO_ROOT / "sql"
_VIEWS_SOURCE = _REPO_ROOT / "docs" / "VIEWS_Customized_final.txt"

# Whitelist - nur diese Dateinamen dürfen ausgeliefert werden. Schuetzt
# vor Path-Traversal-Tricks (../../etc/passwd etc).
_ALLOWED_TEMPLATES = {
    "invoice_header.sql": "Rechnungskopf (Hotel, Kunde, Bank, Profile-IDs)",
    "invoice_lines.sql":  "Rechnungspositionen (1 Zeile = 1 Folio-Posting)",
    "invoice_tax.sql":    "USt-Aufschluesselung pro Steuersatz",
    "invoice_totals.sql": "Brutto-/Netto-/USt-Summen + Prepaid/Payable",
    "invoice_list.sql":   "Liste der Rechnungen pro Zeitraum (UI-Liste)",
}


def _data_dir(state: dict) -> Path:
    dd = state.get("data_dir")
    if dd is None:
        raise HTTPException(500, "data_dir nicht initialisiert")
    return Path(dd)


@router.get("/templates")
def list_templates(state: dict = Depends(get_state)):
    """Liefert Metadaten zu allen verfuegbaren SQL-Templates + Override-Status."""
    try:
        active_overrides = set(sql_overrides.list_overrides(_data_dir(state)))
    except HTTPException:
        active_overrides = set()

    items = []
    for name, desc in _ALLOWED_TEMPLATES.items():
        path = _SQL_DIR / name
        if not path.exists():
            continue
        items.append({
            "name": name,
            "description": desc,
            "size_bytes": path.stat().st_size,
            "url": f"/api/sql/templates/{name}",
            "overridden": name in active_overrides,
            "expected_bind": sql_overrides.ALLOWED_NAMES.get(name, ""),
        })
    return {
        "items": items,
        "note": (
            "Diese SQL-Statements werden direkt vom Poller gegen V8LIVE "
            "ausgefuehrt — sie sind NICHT als VIEW in der DB installiert. "
            "Der App-Datenbankbenutzer braucht nur SELECT-Rechte. "
            "Anpassungen koennen ueber den Editor pro Template "
            "vorgenommen werden (Override wird in slim/data/sql_overrides/ "
            "gespeichert und ueberlebt App-Updates)."
        ),
        "views_source_url": "/api/sql/views-source",
    }


@router.get("/templates/{name}", response_class=PlainTextResponse)
def get_template(name: str, state: dict = Depends(get_state)):
    """Liefert das AKTIVE SQL-Template (Override wenn vorhanden, sonst Repo)."""
    if name not in _ALLOWED_TEMPLATES:
        raise HTTPException(404, f"Unbekanntes Template: {name}")
    # Override hat Vorrang — das ist genau was der Poller auch liest
    override = sql_overrides.load(_data_dir(state), name)
    if override is not None:
        return PlainTextResponse(override,
                                 media_type="text/plain; charset=utf-8")
    path = _SQL_DIR / name
    if not path.exists():
        raise HTTPException(404, f"Datei fehlt: {name}")
    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        media_type="text/plain; charset=utf-8",
    )


@router.get("/templates/{name}/source", response_class=PlainTextResponse)
def get_template_source(name: str):
    """Liefert IMMER die Repo-Vorlage (ohne Override), z.B. fuer Reset-Vorschau."""
    if name not in _ALLOWED_TEMPLATES:
        raise HTTPException(404, f"Unbekanntes Template: {name}")
    path = _SQL_DIR / name
    if not path.exists():
        raise HTTPException(404, f"Datei fehlt: {name}")
    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        media_type="text/plain; charset=utf-8",
    )


class SqlBody(BaseModel):
    sql: str = Field(..., min_length=1, max_length=50_000)


@router.post("/templates/{name}/validate")
def validate_template(name: str, payload: SqlBody):
    """Dry-Run: validiert ein SQL, speichert NICHTS.
    Liefert {ok: bool, error: str|None}."""
    try:
        sql_overrides.validate(payload.sql, name)
    except sql_overrides.SqlValidationError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "error": None}


@router.put("/templates/{name}")
def put_template(name: str, payload: SqlBody,
                 state: dict = Depends(get_state)):
    """Speichert einen Override fuer dieses Template. Wird beim naechsten
    Poll-Lauf statt der Repo-Vorlage genutzt.

    Validierung wirft 400 bei Verstoss (kein DDL/DML, Bindvariable
    da, Length-Cap, etc).
    """
    try:
        sql_overrides.save(_data_dir(state), name, payload.sql)
    except sql_overrides.SqlValidationError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "name": name, "overridden": True}


@router.delete("/templates/{name}")
def delete_template(name: str, state: dict = Depends(get_state)):
    """Loescht den Override = zurueck auf die Repo-Vorlage."""
    if name not in _ALLOWED_TEMPLATES:
        raise HTTPException(404, f"Unbekanntes Template: {name}")
    deleted = sql_overrides.delete(_data_dir(state), name)
    return {"ok": True, "name": name, "deleted": deleted, "overridden": False}


@router.get("/views-source", response_class=PlainTextResponse)
def get_views_source():
    """Liefert das Original-Views-Dokument
    (docs/VIEWS_Customized_final.txt) als reinen Text.

    Diese Datei ist die HISTORISCHE Quelle der Mapping-Logik:
    CREATE VIEW + CREATE FUNCTION fuer den DBA, wenn die Views
    tatsaechlich in der DB installiert werden sollen
    (z.B. fuer eigene Reports / BI-Tools). Die App selbst nutzt die
    Views aber nicht — sie hat den SELECT-Body inline expandiert.
    """
    if not _VIEWS_SOURCE.exists():
        raise HTTPException(404, "VIEWS_Customized_final.txt nicht gefunden")
    return PlainTextResponse(
        _VIEWS_SOURCE.read_text(encoding="utf-8"),
        media_type="text/plain; charset=utf-8",
    )
