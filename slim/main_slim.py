"""
slim/main_slim.py
-----------------
Entry-Point für die Slim-Variante.

WICHTIG: setzt SUITE8_CONFIG_DIR=<repo>/slim/config BEVOR core.config_loader
importiert wird, damit alle nachgelagerten Module (db_connector,
invoice_fetcher, etc.) gegen die Slim-Konfiguration arbeiten.

Service-Profil:
  - NSSM-Name:  Suite8XRechnungSlim
  - Port:       8022 (Big-App ist 8021)
  - Bind:       127.0.0.1
"""
import os
import sys
from pathlib import Path

# Repo-Root in sys.path hängen (modules/, core/, sql/, templates/, validation/
# liegen dort).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Slim-Configdir HART setzen BEVOR irgendwer aus core importiert.
# (setdefault waere falsch — wenn die Variable vom Big-App-NSSM-Service
# oder einer Test-Sitzung schon gesetzt ist, wuerde Slim still mit
# Big-App-Konfig laufen.)
_SLIM_DIR = Path(__file__).resolve().parent
os.environ["SUITE8_CONFIG_DIR"] = str(_SLIM_DIR / "config")

import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.config_loader import load_app_settings, load_hotel_config, CONFIG_DIR
from core.logging_setup import setup_logging

from slim.api_slim import status as status_api
from slim.api_slim import retry as retry_api
from slim.api_slim import config_api as config_api_module
from slim.api_slim import setup_api as setup_api_module
from slim.api_slim import sql_view as sql_view_module
from slim.api_slim import trigger_sql as trigger_sql_module
from slim.api_slim import run_now as run_now_module
from slim.api_slim import update_api as update_api_module
from slim.api_slim import archive_api as archive_api_module
from slim.core_slim import access
from slim.core_slim import audit_jsonl
from slim.core_slim.clock import now_local
from slim.jobs_slim import poller

DATA_DIR = _SLIM_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = _SLIM_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

setup_logging(load_app_settings().get("log_level", "INFO"))
logger = logging.getLogger(__name__)

_VERSION_FILE = _REPO_ROOT / "VERSION"
app_version = _VERSION_FILE.read_text(encoding="utf-8").strip() if _VERSION_FILE.exists() else "?"

app = FastAPI(
    title="Suite8 XRechnung Slim",
    description="Standalone Suite8-Anhang-Poller. Kein Login, kein DB.",
    version=app_version,
)

# IP-Allowlist: wird beim Start gelesen (Konfig-Aenderung => Dienst-Neustart,
# konsistent mit host/port). localhost ist immer erlaubt; leere Liste =>
# effektiv nur localhost, auch wenn host=0.0.0.0 gebunden ist.
_app_settings = load_app_settings()
_ALLOWED_IPS = _app_settings.get("allowed_ips") or []

# Fehlkonfiguration sichtbar machen: LAN-Bind ohne Allowlist sperrt still alle
# Netzwerk-Clients aus (fail-safe) — beim Start einmal warnen.
_lan_warn = access.lan_exposure_warning(
    _app_settings.get("host", "127.0.0.1"), _ALLOWED_IPS)
if _lan_warn:
    logger.warning(_lan_warn)


@app.middleware("http")
async def _ip_allowlist(request, call_next):
    return await access.dispatch(request, call_next, _ALLOWED_IPS)


app.include_router(status_api.router)
app.include_router(retry_api.router)
app.include_router(config_api_module.router)
app.include_router(setup_api_module.router)
app.include_router(sql_view_module.router)
app.include_router(trigger_sql_module.router)
app.include_router(run_now_module.router)
app.include_router(update_api_module.router)
app.include_router(archive_api_module.router)


def _setup_done() -> bool:
    return (CONFIG_DIR / ".setup_done").exists()


@app.get("/")
async def root():
    # Wenn die App noch nicht durch den Setup-Wizard durchgelaufen ist,
    # zeigen wir nicht das Status-UI sondern den Wizard. Das gilt für den
    # Doppelklick-Workflow: User klickt setup_slim.cmd, Browser öffnet
    # http://127.0.0.1:8022/ → landet automatisch im Wizard.
    if not _setup_done():
        return RedirectResponse(url="/setup", status_code=307)
    return FileResponse(str(_SLIM_DIR / "frontend" / "index.html"))


@app.get("/setup")
async def setup_page():
    return FileResponse(str(_SLIM_DIR / "frontend" / "setup.html"))


@app.get("/healthz")
async def healthz():
    return {"ok": True, "version": app_version}


# --- Scheduler ---
_scheduler = AsyncIOScheduler()


def _run_poller_safely():
    """APScheduler-Callback. Updated den Shared-State für das Status-API."""
    state = status_api.get_state()
    try:
        summary = poller.run_once(data_dir=DATA_DIR)
    except Exception as e:
        logger.exception("Poller-Run crashed")
        audit_jsonl.record_safe(
            DATA_DIR, "poller_crash", details={"error": str(e)[:400]},
        )
        summary = {"crash": True, "error": str(e)[:400]}
    state["last_run"] = now_local().isoformat()
    state["last_run_summary"] = summary


@app.on_event("startup")
async def _startup():
    state = status_api.get_state()
    state["data_dir"] = DATA_DIR
    try:
        cfg = load_hotel_config()
        interval = int(cfg.get("suite8_poll_interval_seconds", 30))
    except Exception:
        # Im Setup-Modus ist hotel.json oft noch nicht da — kein Fehler,
        # Poller laeuft erst nach Setup-Abschluss los.
        logger.info("Hotel-Config noch nicht vorhanden — Poller-Start verzoegert")
        interval = 60
    state["interval_seconds"] = interval

    # Poller nur starten wenn Setup wirklich durch ist. Sonst Wizard-Modus —
    # da soll der Poller nicht ohne Konfig laufen und Audit-Crashes erzeugen.
    if _setup_done():
        _scheduler.add_job(
            _run_poller_safely,
            trigger=IntervalTrigger(seconds=interval),
            id="slim_suite8_attach_poller",
            max_instances=1, coalesce=True, misfire_grace_time=60,
            replace_existing=True,
        )
        _scheduler.start()
        logger.info("Slim-Poller registriert (interval=%ds, data_dir=%s)",
                    interval, DATA_DIR)
    else:
        logger.info("Setup nicht abgeschlossen — Poller nicht gestartet. "
                    "Browser auf %s öffnen, um Setup-Wizard zu starten.",
                    f"http://127.0.0.1:{load_app_settings().get('port', 8022)}/")


@app.on_event("shutdown")
async def _shutdown():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


if __name__ == "__main__":
    import uvicorn
    settings = load_app_settings()
    uvicorn.run(
        "slim.main_slim:app",
        host=settings.get("host", "127.0.0.1"),
        port=int(settings.get("port", 8022)),
        log_level=str(settings.get("log_level", "info")).lower(),
    )
