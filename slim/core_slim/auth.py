"""
slim/core_slim/auth.py
----------------------
Anmeldung fuer die Slim-Oberflaeche: Benutzer (slim/data/users.json),
Passwort-Hash (PBKDF2-SHA256), Sitzungen im Speicher, Sperre bei
Fehlversuchen. Zwei Rollen: 'ansehen' und 'verwalten'.

Ein Neustart beendet alle Sitzungen (gewollt: kein Sitzungs-Speicher auf
der Platte).
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Callable, Optional

ROLES = ("ansehen", "verwalten")
MIN_PASSWORD_LEN = 10
_ITERATIONS = 260_000


class AuthError(Exception):
    pass


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = str(stored).split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"),
                                     bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def _check_password(pw: str) -> None:
    if not isinstance(pw, str) or len(pw) < MIN_PASSWORD_LEN:
        raise AuthError(f"Passwort muss mindestens {MIN_PASSWORD_LEN} Zeichen haben.")


class UserStore:
    """Benutzer in einer JSON-Datei: {name: {hash, role, must_change}}."""

    def __init__(self, path: Path):
        self.path = Path(path)
        # RLock: Lesen und Schreiben laufen unter derselben Sperre, damit unter
        # Windows os.replace nie auf eine gerade gelesene Datei trifft.
        self._lock = threading.RLock()
        self._cache: tuple = (None, {})

    def _load(self) -> dict:
        with self._lock:
            return self._load_locked()

    def _load_locked(self) -> dict:
        if not self.path.exists():
            return {}
        mtime = self.path.stat().st_mtime_ns
        if self._cache[0] == mtime:
            return json.loads(json.dumps(self._cache[1]))   # Kopie
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise AuthError(f"Benutzerdatei {self.path} nicht lesbar: {e}") from e
        if not isinstance(data, dict):
            raise AuthError(f"Benutzerdatei {self.path} hat ein ungueltiges Format.")
        self._cache = (mtime, json.loads(json.dumps(data)))
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        # Cache direkt mit dem geschriebenen Stand fuellen: zwei Schreibvorgaenge
        # kurz hintereinander koennen dieselbe mtime haben (Windows-Aufloesung).
        self._cache = (self.path.stat().st_mtime_ns, json.loads(json.dumps(data)))

    def count(self) -> int:
        return len(self._load())

    def list(self) -> list[dict]:
        return [{"name": n, "role": u.get("role"), "must_change": bool(u.get("must_change"))}
                for n, u in sorted(self._load().items())]

    def get(self, name: str) -> Optional[dict]:
        u = self._load().get(name)
        return dict(u, name=name) if u else None

    def _admins(self, data: dict) -> int:
        return sum(1 for u in data.values() if u.get("role") == "verwalten")

    def create(self, name: str, pw: str, role: str, must_change: bool = True,
               only_if_empty: bool = False) -> None:
        name = (name or "").strip()
        if not name or len(name) > 64:
            raise AuthError("Benutzername fehlt oder ist zu lang.")
        if role not in ROLES:
            raise AuthError(f"Unbekannte Rolle {role!r}.")
        _check_password(pw)
        with self._lock:
            data = self._load()
            if only_if_empty and data:
                raise AuthError("Es gibt bereits Benutzer.")
            if name in data:
                raise AuthError(f"Benutzer {name!r} gibt es schon.")
            data[name] = {"hash": hash_password(pw), "role": role, "must_change": must_change}
            self._save(data)

    def set_password(self, name: str, pw: str, must_change: bool = False) -> None:
        _check_password(pw)
        with self._lock:
            data = self._load()
            if name not in data:
                raise AuthError(f"Benutzer {name!r} unbekannt.")
            data[name].update(hash=hash_password(pw), must_change=must_change)
            self._save(data)

    def set_role(self, name: str, role: str) -> None:
        if role not in ROLES:
            raise AuthError(f"Unbekannte Rolle {role!r}.")
        with self._lock:
            data = self._load()
            if name not in data:
                raise AuthError(f"Benutzer {name!r} unbekannt.")
            if data[name].get("role") == "verwalten" and role != "verwalten" and self._admins(data) <= 1:
                raise AuthError("Der letzte Verwalter kann nicht herabgestuft werden.")
            data[name]["role"] = role
            self._save(data)

    def delete(self, name: str) -> None:
        with self._lock:
            data = self._load()
            if name not in data:
                raise AuthError(f"Benutzer {name!r} unbekannt.")
            if data[name].get("role") == "verwalten" and self._admins(data) <= 1:
                raise AuthError("Der letzte Verwalter kann nicht geloescht werden.")
            del data[name]
            self._save(data)


class SessionStore:
    """Sitzungen im Speicher, Ablauf nach `ttl_seconds` ohne Aktivitaet."""

    def __init__(self, ttl_seconds: int = 8 * 3600, clock: Callable[[], float] = time.monotonic):
        self.ttl, self.clock = ttl_seconds, clock
        self._s: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, name: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._s[token] = {"user": name, "seen": self.clock()}
        return token

    def get(self, token: Optional[str]) -> Optional[dict]:
        if not token:
            return None
        with self._lock:
            s = self._s.get(token)
            if not s:
                return None
            if self.clock() - s["seen"] > self.ttl:
                del self._s[token]
                return None
            s["seen"] = self.clock()
            return dict(s)

    def drop(self, token: Optional[str]) -> None:
        with self._lock:
            self._s.pop(token or "", None)

    def drop_user(self, name: str) -> None:
        with self._lock:
            for t in [t for t, s in self._s.items() if s["user"] == name]:
                del self._s[t]


class LoginGuard:
    """Sperrt einen Schluessel (z. B. 'IP|Benutzer') fuer `window` Sekunden,
    sobald innerhalb von `window` Sekunden `limit` Fehlversuche auflaufen.
    Die Zahl der gemerkten Schluessel ist begrenzt (`max_keys`)."""

    def __init__(self, limit: int = 5, window: int = 15 * 60,
                 clock: Callable[[], float] = time.monotonic, max_keys: int = 10_000):
        self.limit, self.window, self.clock, self.max_keys = limit, window, clock, max_keys
        self._fails: dict[str, list[float]] = {}
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    def blocked(self, key: str) -> bool:
        with self._lock:
            until = self._until.get(key)
            if until is None:
                return False
            if self.clock() >= until:
                del self._until[key]
                return False
            return True

    def fail(self, key: str) -> None:
        with self._lock:
            now = self.clock()
            fails = [t for t in self._fails.get(key, []) if now - t <= self.window] + [now]
            if len(fails) >= self.limit:
                self._until[key] = now + self.window
                self._fails.pop(key, None)
            else:
                self._fails[key] = fails
            # Begrenzen, ohne aktive Sperren zu verdraengen: zuerst Abgelaufenes
            # weg, dann die aeltesten Fehlversuchs-Zaehler (keine Sperren).
            if len(self._until) > self.max_keys:
                for k in [k for k, u in self._until.items() if u <= now]:
                    del self._until[k]
            # Harte Obergrenze (Speicher): erst beim Zehnfachen, dann die
            # Sperren, die am fruehesten ohnehin ablaufen.
            hard = self.max_keys * 10
            if len(self._until) > hard:
                for k, _ in sorted(self._until.items(), key=lambda kv: kv[1])[:len(self._until) - hard]:
                    del self._until[k]
            while len(self._fails) > self.max_keys:
                self._fails.pop(next(iter(self._fails)))

    def ok(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
            self._until.pop(key, None)
