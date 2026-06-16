"""
slim/core_slim/updater.py
-------------------------
Auto-Updater für die Slim-App über GitHub.

Strategie: **inkrementell auf Datei-Ebene** — es wird KEIN Release-ZIP geladen.
Stattdessen ermittelt der Updater über die GitHub Compare-API genau die seit
der laufenden Version geänderten Dateien (added/modified/removed) und holt nur
diese einzeln über die Contents-API (raw). Vorteile:
- minimaler Download (nur Diff statt ~150 MB ZIP)
- gelöschte Dateien werden sauber mit-entfernt
- funktioniert öffentlich UND privat (PAT) über die API

Quelle: github.com/ahornhotels/XRechnung_Slim (Releases mit Tag = VERSION)

State wird in `slim/data/update_state.json` persistiert.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from core.config_loader import load_json, CONFIG_DIR
from core.crypto import load_key, decrypt

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Slim-Pfad-Struktur: <APP_ROOT>/slim, install/, validation/, ...
APP_ROOT = Path(__file__).resolve().parent.parent.parent
VERSION_FILE = APP_ROOT / "VERSION"
NSSM_EXE = APP_ROOT / "install" / "nssm.exe"
SERVICE_NAME = "Suite8XRechnungSlim"

DEFAULT_OWNER = "ahornhotels"
DEFAULT_REPO = "XRechnung_Slim"

# Pfade die beim Update NIE überschrieben/gelöscht werden.
PRESERVE = {
    # Slim-spezifische Runtime + User-Configs
    "slim/config",
    "slim/data",
    "slim/logs",
    # Eingebautes Python/JRE/Client mit installierten Paketen — würde die App
    # beim Überschreiben zerstören. Bleibt unangetastet.
    "install/python",
    "install/jre",
    "install/wheels",
    "install/instantclient",
    "install/nssm.exe",
    # KoSIT-Material (groß, kommt selten neu)
    "validation",
    ".venv",
    ".git",
    ".pytest_cache",
    "__pycache__",
}

# Top-Level-Pfade die beim Update überhaupt angefasst werden. Nur was hier
# drin ist UND nicht in PRESERVE fällt, wird kopiert/gelöscht.
UPDATE_TARGETS = {
    "slim",
    "modules",
    "core",
    "sql",
    "templates",
    "docs",
    "VERSION",
    "LICENSE",
    "README.md",
    "requirements.txt",
    "requirements-dev.txt",
    "pytest.ini",
}

STATE_FILE = APP_ROOT / "slim" / "data" / "update_state.json"


class UpdateError(Exception):
    pass


class CompareUnavailable(Exception):
    """Compare-API konnte den Diff nicht liefern (z.B. Base-Tag unbekannt).
    Signalisiert dem Aufrufer, auf den vollen Tree-Abgleich auszuweichen."""


# ─────────────────────────── Versions-Helfer ───────────────────────────

def current_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return "0.0.0"


def _parse_version(tag: str) -> tuple:
    """'v1.5.0' -> (1, 5, 0) für Vergleich. Bei Parse-Fehler: (0,0,0)."""
    s = tag.lstrip("vV")
    parts = re.findall(r"\d+", s)
    return tuple(int(p) for p in parts[:3]) + (0,) * (3 - len(parts[:3]))


def load_state() -> dict:
    """Letzter Update-Zustand. Tolerant bei Fehlern."""
    if not STATE_FILE.exists():
        return {"last_version": None, "last_tag": None,
                "applied_at": None, "release_url": None}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("update_state.json beschaedigt: %s", e)
        return {"last_version": None, "last_tag": None,
                "applied_at": None, "release_url": None}


def save_state(data: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ─────────────────────────── Konfiguration ───────────────────────────

def load_update_config() -> dict:
    """Lädt slim/config/update.json, fügt Defaults hinzu. Token wird
    entschlüsselt wenn vorhanden.

    Default: Updates aktiviert, öffentliches Repo ahornhotels/XRechnung_Slim.
    Wer ein anderes / privates Repo will: update.json anlegen (+ PAT).
    """
    cfg = load_json(CONFIG_DIR / "update.json", default={}) or {}
    cfg.setdefault("enabled", True)
    cfg.setdefault("owner", DEFAULT_OWNER)
    cfg.setdefault("repo", DEFAULT_REPO)
    if cfg.get("pat_token"):
        key_path = CONFIG_DIR / "connection.key"
        if key_path.exists():
            try:
                cfg["pat_token_plain"] = decrypt(
                    cfg["pat_token"], load_key(key_path),
                )
            except Exception as e:
                logger.warning("PAT-Entschluesselung fehlgeschlagen: %s", e)
    return cfg


def _gh_headers(cfg: dict, accept: str = "application/vnd.github+json") -> dict:
    h = {
        "Accept": accept,
        "User-Agent": "XRechnungSlim-Updater/2.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if cfg.get("pat_token_plain"):
        h["Authorization"] = f"Bearer {cfg['pat_token_plain']}"
    return h


# ─────────────────────────── GitHub-Calls ───────────────────────────

def fetch_latest_release(cfg: Optional[dict] = None) -> dict:
    """GET /releases/latest. Liefert release-Dict (oder wirft UpdateError)."""
    if cfg is None:
        cfg = load_update_config()
    if not cfg.get("enabled"):
        raise UpdateError("Updates sind deaktiviert (update.json: enabled=false)")

    owner = cfg.get("owner") or DEFAULT_OWNER
    repo = cfg.get("repo") or DEFAULT_REPO
    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases/latest"
    logger.info("GitHub: GET %s", url)
    try:
        resp = httpx.get(url, headers=_gh_headers(cfg), timeout=15.0,
                         follow_redirects=True)
    except httpx.HTTPError as e:
        raise UpdateError(f"GitHub nicht erreichbar: {e}")

    if resp.status_code == 404:
        raise UpdateError(
            f"Kein Release im Repo {owner}/{repo} gefunden. "
            "Privates Repo? Dann PAT-Token konfigurieren."
        )
    if resp.status_code == 401:
        raise UpdateError("PAT ungueltig (401)")
    if resp.status_code == 403:
        raise UpdateError("Rate-Limit oder fehlende Rechte (403)")
    if resp.status_code >= 400:
        raise UpdateError(f"GitHub API {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def check_for_update(cfg: Optional[dict] = None) -> dict:
    """Liefert {current_version, latest_version, latest_tag, available,
    release_url, release_notes, error?}. Reine Versions-Pruefung — der
    eigentliche Datei-Diff entsteht erst beim Apply."""
    if cfg is None:
        cfg = load_update_config()

    result = {
        "current_version": current_version(),
        "latest_version": None,
        "latest_tag": None,
        "release_url": None,
        "release_notes": None,
        "available": False,
    }
    if not cfg.get("enabled"):
        result["error"] = "Updates sind deaktiviert"
        return result

    try:
        release = fetch_latest_release(cfg)
    except UpdateError as e:
        result["error"] = str(e)
        return result

    tag = release.get("tag_name") or ""
    result["latest_tag"] = tag
    result["latest_version"] = tag.lstrip("vV")
    result["release_url"] = release.get("html_url")
    result["release_notes"] = (release.get("body") or "")[:2000]

    cur = _parse_version(result["current_version"])
    latest = _parse_version(result["latest_version"])
    result["available"] = latest > cur
    return result


def compare_changed_files(base: str, head: str, cfg: dict) -> list:
    """GET /compare/{base}...{head} → Liste geänderter Dateien.

    Jedes Element: ``{"filename", "status", "previous_filename"?}``.
    Status ist u.a. added/modified/removed/renamed.

    Raises:
        CompareUnavailable: bei 404 (Base- oder Head-Ref unbekannt) — der
            Aufrufer soll dann auf den vollen Tree-Abgleich ausweichen.
        UpdateError: bei sonstigen API-Fehlern.
    """
    owner = cfg.get("owner") or DEFAULT_OWNER
    repo = cfg.get("repo") or DEFAULT_REPO
    url = f"{GITHUB_API}/repos/{owner}/{repo}/compare/{base}...{head}"
    logger.info("GitHub: GET %s", url)
    try:
        resp = httpx.get(url, headers=_gh_headers(cfg), timeout=30.0,
                         follow_redirects=True)
    except httpx.HTTPError as e:
        raise UpdateError(f"GitHub nicht erreichbar: {e}")

    if resp.status_code == 404:
        raise CompareUnavailable(f"Compare {base}...{head} nicht moeglich (404)")
    if resp.status_code >= 400:
        raise UpdateError(f"Compare API {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    files = data.get("files") or []
    return [
        {"filename": f.get("filename", ""),
         "status": f.get("status", "modified"),
         "previous_filename": f.get("previous_filename")}
        for f in files if f.get("filename")
    ]


def list_repo_files(ref: str, cfg: dict) -> list:
    """GET /git/trees/{ref}?recursive=1 → alle Blob-Pfade (Fallback fuer den
    vollen Abgleich, wenn kein Base-Tag fuer ein Compare bekannt ist)."""
    owner = cfg.get("owner") or DEFAULT_OWNER
    repo = cfg.get("repo") or DEFAULT_REPO
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{ref}?recursive=1"
    logger.info("GitHub: GET %s", url)
    try:
        resp = httpx.get(url, headers=_gh_headers(cfg), timeout=30.0,
                         follow_redirects=True)
    except httpx.HTTPError as e:
        raise UpdateError(f"GitHub nicht erreichbar: {e}")
    if resp.status_code >= 400:
        raise UpdateError(f"Tree API {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return [t["path"] for t in data.get("tree", []) if t.get("type") == "blob"]


def download_file_raw(path: str, ref: str, cfg: dict) -> bytes:
    """GET /contents/{path}?ref={ref} mit Accept=raw → Datei-Bytes.
    Funktioniert öffentlich und (mit PAT) privat."""
    owner = cfg.get("owner") or DEFAULT_OWNER
    repo = cfg.get("repo") or DEFAULT_REPO
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}?ref={ref}"
    headers = _gh_headers(cfg, accept="application/vnd.github.raw")
    try:
        resp = httpx.get(url, headers=headers, timeout=60.0,
                         follow_redirects=True)
    except httpx.HTTPError as e:
        raise UpdateError(f"Download fehlgeschlagen ({path}): {e}")
    if resp.status_code >= 400:
        raise UpdateError(f"Download {path}: HTTP {resp.status_code}")
    return resp.content


# ─────────────────────────── Filter / Apply ───────────────────────────

def _path_in_preserve(rel_path: str) -> bool:
    """Prüft ob ein Pfad (relativ zum App-Root) in PRESERVE fällt
    (Prefix-Match auf Pfad-Segment-Ebene)."""
    parts = rel_path.replace("\\", "/").split("/")
    for i in range(1, len(parts) + 1):
        if "/".join(parts[:i]) in PRESERVE:
            return True
    return parts[0] in PRESERVE


def _should_update(rel_path: str) -> bool:
    """True, wenn der Pfad beim Update angefasst werden darf: Top-Level in
    UPDATE_TARGETS UND nicht in PRESERVE."""
    top = rel_path.replace("\\", "/").split("/", 1)[0]
    if top not in UPDATE_TARGETS:
        return False
    return not _path_in_preserve(rel_path)


def _write_file(rel: str, data: bytes, stats: dict) -> None:
    """Schreibt eine Datei nach APP_ROOT/rel. Bei Lock (.py vom laufenden
    Service offen): als .new ablegen, greift beim naechsten Restart."""
    dst = APP_ROOT / rel
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            try:
                dst.unlink()
            except PermissionError:
                (dst.with_suffix(dst.suffix + ".new")).write_bytes(data)
                stats["failed"].append(f"{rel} (-> .new)")
                return
        dst.write_bytes(data)
        stats["copied"].append(rel)
    except Exception as e:
        logger.exception("Konnte %s nicht schreiben", rel)
        stats["failed"].append(f"{rel}: {e}")


def apply_incremental_update(files: list, head_ref: str, cfg: dict,
                             dry_run: bool = False) -> dict:
    """Wendet die geänderten Dateien an: added/modified → herunterladen und
    schreiben, removed → lokal löschen. PRESERVE/UPDATE_TARGETS werden
    granular durchgesetzt."""
    stats = {"copied": [], "preserved": [], "deleted": [], "failed": [],
             "dry_run": dry_run}

    for f in files:
        rel = f["filename"].replace("\\", "/")
        status = f.get("status", "modified")
        top = rel.split("/", 1)[0]

        # Top-Level gar nicht relevant -> komplett ignorieren
        if top not in UPDATE_TARGETS:
            continue
        # In PRESERVE -> niemals anfassen
        if _path_in_preserve(rel):
            stats["preserved"].append(rel)
            continue

        if status == "removed":
            if dry_run:
                stats["deleted"].append(rel)
                continue
            dst = APP_ROOT / rel
            try:
                if dst.exists():
                    dst.unlink()
                stats["deleted"].append(rel)
            except Exception as e:
                stats["failed"].append(f"{rel} (delete): {e}")
            continue

        # added / modified / renamed / changed
        if dry_run:
            stats["copied"].append(rel)
            continue
        try:
            data = download_file_raw(rel, head_ref, cfg)
        except UpdateError as e:
            stats["failed"].append(str(e))
            continue
        _write_file(rel, data, stats)

        # Bei Rename die alte Datei zusätzlich entfernen
        prev = f.get("previous_filename")
        if status == "renamed" and prev and _should_update(prev):
            old = APP_ROOT / prev
            try:
                if old.exists():
                    old.unlink()
                stats["deleted"].append(prev)
            except Exception as e:
                stats["failed"].append(f"{prev} (delete): {e}")

    return stats


# ─────────────────────────── Service-Restart ───────────────────────────

def restart_service_detached() -> None:
    """NSSM-Restart in einem detached cmd-Wrapper, ~4s Delay damit der
    HTTP-Request des Apply noch zustellt."""
    if not NSSM_EXE.exists():
        logger.info("NSSM nicht gefunden — kein automatischer Restart")
        return

    log_path = APP_ROOT / "slim" / "data" / "updater_restart.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd_str = (
        f'ping -n 5 127.0.0.1 > nul && '
        f'"{NSSM_EXE}" restart {SERVICE_NAME} >> "{log_path}" 2>&1'
    )
    flags = (subprocess.DETACHED_PROCESS
             | subprocess.CREATE_NEW_PROCESS_GROUP
             | 0x01000000)  # CREATE_BREAKAWAY_FROM_JOB
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", cmd_str],
            creationflags=flags,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("Service-Restart in ~4s angestossen, Log: %s", log_path.name)
    except Exception as e:
        logger.error("Restart-Spawn fehlgeschlagen: %s", e)


# ─────────────────────────── Orchestrierung ───────────────────────────

def _resolve_base_ref(cfg: dict) -> Optional[str]:
    """Bestimmt den Base-Ref fuer das Compare: bevorzugt der zuletzt
    angewandte Tag (aus dem State), sonst 'v<aktuelle VERSION>'. None, wenn
    keine sinnvolle Ausgangsversion bekannt ist (-> voller Abgleich)."""
    last_tag = (load_state() or {}).get("last_tag")
    if last_tag:
        return last_tag
    cur = current_version()
    if _parse_version(cur) == (0, 0, 0):
        return None
    return f"v{cur}"


def perform_full_update(cfg: Optional[dict] = None) -> dict:
    """Check + (Compare-Diff oder Tree-Fallback) + Apply + State + Restart."""
    if cfg is None:
        cfg = load_update_config()
    check = check_for_update(cfg)
    if check.get("error"):
        raise UpdateError(check["error"])
    if not check["available"]:
        return {
            "applied": False,
            "current_version": check["current_version"],
            "latest_version": check["latest_version"],
            "message": "Bereits aktuell — kein Update angewendet.",
        }

    head = check["latest_tag"]
    base = _resolve_base_ref(cfg)
    mode = "incremental"
    files = None
    if base:
        try:
            files = compare_changed_files(base, head, cfg)
        except CompareUnavailable:
            files = None
    if files is None:
        # Fallback: voller Datei-für-Datei-Abgleich (immer noch kein ZIP).
        mode = "full"
        files = [{"filename": p, "status": "modified"}
                 for p in list_repo_files(head, cfg)]

    stats = apply_incremental_update(files, head, cfg)

    save_state({
        "last_version": check["latest_version"],
        "last_tag": check["latest_tag"],
        "release_url": check["release_url"],
        "applied_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })

    restart_service_detached()

    return {
        "applied": True,
        "mode": mode,
        "from_version": check["current_version"],
        "to_version": check["latest_version"],
        "copied": stats["copied"],
        "deleted": stats["deleted"],
        "preserved": stats["preserved"],
        "failed": stats["failed"],
        "message": f"Update angewendet ({mode}), Service startet in ~4 Sekunden neu.",
    }
