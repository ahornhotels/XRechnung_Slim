"""
slim/api_slim/auth_api.py
-------------------------
Anmeldung der Slim-Oberflaeche: Middleware (Sitzung und Rolle pruefen) und
Endpunkte unter /api/auth.

Rollen:
  ansehen   - alle GET-Anfragen ausser SQL, Konfiguration, Einstellungen und
              Benutzer
  verwalten - alles

Ersteinrichtung: Gibt es keinen Benutzer, kann nur ein Zugriff von localhost
den ersten Verwalter anlegen (POST /api/auth/bootstrap). Der Poller laeuft
davon unabhaengig weiter.
"""
import logging
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from slim.core_slim import audit_jsonl, auth

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USERS = auth.UserStore(DATA_DIR / "users.json")
SESSIONS = auth.SessionStore()
GUARD = auth.LoginGuard()
COOKIE = "slim_session"

# Ohne Anmeldung erreichbar (Setup hat seinen eigenen Schutz: _require_setup_mode)
_PUBLIC = {"/healthz", "/login", "/api/auth/login", "/api/auth/state",
           "/api/auth/bootstrap", "/favicon.ico"}
# Fuer jeden angemeldeten Benutzer, auch bei must_change und mit Rolle ansehen
_SELF = {"/api/auth/logout", "/api/auth/password"}
# Auch lesend nur fuer 'verwalten'
_ADMIN_PREFIXES = ("/api/sql", "/api/config", "/api/settings", "/api/users", "/api/system",
                   "/api/trigger-sql", "/api/overrides", "/api/wmai/", "/api/setup", "/setup")
# Gleicher Aufwand wie eine echte Pruefung, damit unbekannte Benutzernamen
# nicht an der Antwortzeit erkennbar sind.
_DUMMY_HASH = auth.hash_password("dummy-passwort-zum-zeitausgleich")


# Am Server (localhost) gibt es keine Sperre, aber je Benutzername hoechstens
# einen Versuch pro Sekunde. Zu fruehe Versuche werden sofort mit 429
# abgelehnt (kein Warten, kein Thread blockiert, keine Passwortpruefung). Ein
# erfolgreicher Versuch gibt den Platz sofort frei; Fehlversuche mit anderen
# (z. B. unbekannten) Namen beruehren den Platz eines echten Kontos nicht.
_LOCAL_RATE_LOCK = threading.Lock()
_LOCAL_NEXT: dict[str, float] = {}
_LOCAL_INTERVAL = 1.0
_LOCAL_MAX_KEYS = 10_000


def _local_slot_free(name: str) -> bool:
    """Reserviert den naechsten lokalen Versuch fuer `name`; False = zu frueh."""
    with _LOCAL_RATE_LOCK:
        now = time.monotonic()
        if now < _LOCAL_NEXT.get(name, 0.0):
            return False
        if len(_LOCAL_NEXT) >= _LOCAL_MAX_KEYS:
            for k in [k for k, t in _LOCAL_NEXT.items() if t <= now]:
                del _LOCAL_NEXT[k]
        _LOCAL_NEXT[name] = now + _LOCAL_INTERVAL
        return True


def _local_slot_release(name: str) -> None:
    with _LOCAL_RATE_LOCK:
        _LOCAL_NEXT.pop(name, None)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _is_local(request: Request) -> bool:
    from slim.core_slim.access import _parse_ip   # normalisiert ::ffff:a.b.c.d
    host = request.client.host if request.client else ""
    ip = _parse_ip(host)
    return bool(ip and ip.is_loopback) or host == "localhost"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _needs_admin(method: str, path: str) -> bool:
    return (method not in ("GET", "HEAD", "OPTIONS") and path not in _SELF) \
        or path.startswith(_ADMIN_PREFIXES)


def _audit(event: str, **details) -> None:
    audit_jsonl.record_safe(DATA_DIR, event, details=details)


def _deny(request: Request, status: int, detail: str):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": detail}, status_code=status)
    return RedirectResponse("/login", status_code=303)


def _setup_done() -> bool:
    from core.config_loader import CONFIG_DIR
    return (CONFIG_DIR / ".setup_done").exists()


async def middleware(request: Request, call_next):
    path = request.url.path
    if path in _PUBLIC:
        return await call_next(request)
    if not _setup_done() and _is_local(request) and USERS.count() == 0:
        # Ersteinrichtung am Server: Der Wizard (/setup, /api/setup/*,
        # /api/config/pattern/*) laeuft ohne Anmeldung - es gibt noch keine
        # Benutzer. Nur lokal und nur, solange niemand angelegt ist.
        return await call_next(request)
    sess = SESSIONS.get(request.cookies.get(COOKIE))
    user = USERS.get(sess["user"]) if sess else None
    if not user:
        return _deny(request, 401, "Nicht angemeldet")
    if user.get("must_change") and path not in _SELF:
        return _deny(request, 403, "Passwort muss geaendert werden")
    if _needs_admin(request.method, path) and user.get("role") != "verwalten":
        return _deny(request, 403, "Keine Berechtigung (Rolle 'verwalten' noetig)")
    request.state.user = user["name"]
    request.state.role = user.get("role")
    return await call_next(request)


class LoginPayload(BaseModel):
    username: str
    password: str


class PasswordPayload(BaseModel):
    old: str
    new: str


def current_user(request: Request) -> dict | None:
    sess = SESSIONS.get(request.cookies.get(COOKIE))
    return USERS.get(sess["user"]) if sess else None


@router.get("/state")
def state(request: Request):
    user = current_user(request)
    return {
        "users_exist": USERS.count() > 0,
        "logged_in": bool(user),
        "user": user["name"] if user else None,
        "role": user.get("role") if user else None,
        "must_change": bool(user.get("must_change")) if user else False,
        "local": _is_local(request),
        "setup_done": _setup_done(),
    }


@router.post("/login")
def login(payload: LoginPayload, request: Request):
    name = payload.username.strip()
    fail = HTTPException(401, "Anmeldung fehlgeschlagen")
    # Sperre je Adresse UND Benutzer: ein Dritter im Netz kann den Verwalter
    # nicht aussperren (andere Adresse = eigener Zaehler). Am Server selbst
    # teilen sich alle Sitzungen (z. B. RDP) 127.0.0.1 - dort keine Sperre,
    # sondern hoechstens ein Versuch pro Sekunde (_local_slot_free).
    local = _is_local(request)
    key = f"{_client_ip(request)}|{name[:64]}"
    if not local and GUARD.blocked(key):
        _audit("login_blocked", user=name, ip=_client_ip(request))
        raise fail
    if local and not _local_slot_free(name[:64]):
        _audit("login_throttled", user=name)
        raise HTTPException(429, "Bitte eine Sekunde warten und erneut versuchen")
    user = USERS.get(name)
    ok = auth.verify_password(payload.password, user["hash"] if user else _DUMMY_HASH)
    if not user or not ok:
        if not local:
            GUARD.fail(key)
        _audit("login_failed", user=name, ip=_client_ip(request))
        raise fail
    GUARD.ok(key)
    if local:
        _local_slot_release(name[:64])
    token = SESSIONS.create(name)
    _audit("login_ok", user=name)
    resp = JSONResponse({"ok": True, "role": user.get("role"),
                         "must_change": bool(user.get("must_change"))})
    resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
    return resp


@router.post("/logout")
def logout(request: Request):
    user = current_user(request)
    SESSIONS.drop(request.cookies.get(COOKIE))
    if user:
        _audit("logout", user=user["name"])
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.post("/password")
def change_password(payload: PasswordPayload, request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Nicht angemeldet")
    if not auth.verify_password(payload.old, user["hash"]):
        raise HTTPException(400, "Bisheriges Passwort falsch")
    try:
        USERS.set_password(user["name"], payload.new, must_change=False)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    # Alle Sitzungen des Benutzers beenden (z. B. eine fremde nach einem
    # Passwort-Leck) und dieser Anfrage eine neue Sitzung geben.
    SESSIONS.drop_user(user["name"])
    token = SESSIONS.create(user["name"])
    _audit("password_changed", user=user["name"])
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
    return resp


@router.post("/bootstrap")
def bootstrap(payload: LoginPayload, request: Request):
    """Ersten Verwalter anlegen - nur ohne Benutzer und nur von localhost."""
    forbidden = HTTPException(403, "Ersteinrichtung nur am Server und nur ohne Benutzer moeglich")
    if USERS.count() > 0 or not _is_local(request):
        raise forbidden
    try:
        USERS.create(payload.username, payload.password, "verwalten", must_change=False,
                     only_if_empty=True)
    except auth.AuthError as e:
        if "bereits Benutzer" in str(e):
            raise forbidden
        raise HTTPException(400, str(e))
    _audit("bootstrap_admin", user=payload.username.strip())
    return {"ok": True}


# --- Benutzerverwaltung (nur 'verwalten', siehe _ADMIN_PREFIXES) ------------

users_router = APIRouter(prefix="/api/users", tags=["users"])


class NewUser(BaseModel):
    name: str
    password: str
    role: str = "ansehen"


class UserChange(BaseModel):
    role: str | None = None
    password: str | None = None


def _actor(request: Request) -> str:
    return getattr(request.state, "user", None) or "?"


@users_router.get("")
def list_users():
    return USERS.list()


@users_router.post("")
def create_user(payload: NewUser, request: Request):
    try:
        USERS.create(payload.name, payload.password, payload.role, must_change=True)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    _audit("user_created", user=payload.name.strip(), role=payload.role, by=_actor(request))
    return {"ok": True}


@users_router.put("/{name}")
def change_user(name: str, payload: UserChange, request: Request):
    if USERS.get(name) is None:
        raise HTTPException(404, "Benutzer unbekannt")
    try:
        if payload.role is not None:
            USERS.set_role(name, payload.role)
        if payload.password:
            # Vom Verwalter gesetzt: der Benutzer muss es bei der naechsten
            # Anmeldung aendern; laufende Sitzungen enden.
            USERS.set_password(name, payload.password, must_change=True)
            SESSIONS.drop_user(name)
    except auth.AuthError as e:
        status = 409 if "letzte Verwalter" in str(e) else 400
        raise HTTPException(status, str(e))
    # Eine Rollenaenderung wirkt sofort: die Middleware liest die Rolle bei
    # jeder Anfrage neu aus der Benutzerdatei.
    _audit("user_changed", user=name, role=payload.role,
           password_reset=bool(payload.password), by=_actor(request))
    return {"ok": True}


@users_router.delete("/{name}")
def delete_user(name: str, request: Request):
    try:
        USERS.delete(name)
    except auth.AuthError as e:
        status = 409 if "letzte Verwalter" in str(e) else 404
        raise HTTPException(status, str(e))
    SESSIONS.drop_user(name)
    _audit("user_deleted", user=name, by=_actor(request))
    return {"ok": True}
