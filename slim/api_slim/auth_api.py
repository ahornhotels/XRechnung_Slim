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
import ipaddress
import logging
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
           "/api/auth/bootstrap", "/setup", "/favicon.ico"}
_PUBLIC_PREFIXES = ("/api/setup/", "/static/login")
# Fuer jeden angemeldeten Benutzer, auch bei must_change und mit Rolle ansehen
_SELF = {"/api/auth/logout", "/api/auth/password"}
# Auch lesend nur fuer 'verwalten'
_ADMIN_PREFIXES = ("/api/sql", "/api/config", "/api/settings", "/api/users", "/api/system")

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost",)


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
    if path in _PUBLIC or path.startswith(_PUBLIC_PREFIXES):
        return await call_next(request)
    if path == "/" and not _setup_done():
        return await call_next(request)   # leitet auf den Setup-Wizard um
    sess = SESSIONS.get(request.cookies.get(COOKIE))
    user = USERS.get(sess["user"]) if sess else None
    if not user:
        return _deny(request, 401, "Nicht angemeldet")
    if user.get("must_change") and path not in _SELF:
        return _deny(request, 403, "Passwort muss geaendert werden")
    needs_admin = (request.method not in ("GET", "HEAD", "OPTIONS") and path not in _SELF) \
        or path.startswith(_ADMIN_PREFIXES)
    if needs_admin and user.get("role") != "verwalten":
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
    if GUARD.blocked(name):
        _audit("login_blocked", user=name)
        raise fail
    user = USERS.get(name)
    if not user or not auth.verify_password(payload.password, user["hash"]):
        GUARD.fail(name)
        _audit("login_failed", user=name)
        raise fail
    GUARD.ok(name)
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
    _audit("password_changed", user=user["name"])
    return {"ok": True}


@router.post("/bootstrap")
def bootstrap(payload: LoginPayload, request: Request):
    """Ersten Verwalter anlegen - nur ohne Benutzer und nur von localhost."""
    if USERS.count() > 0 or not _is_local(request):
        raise HTTPException(403, "Ersteinrichtung nur am Server und nur ohne Benutzer moeglich")
    try:
        USERS.create(payload.username, payload.password, "verwalten", must_change=False)
    except auth.AuthError as e:
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
