"""
slim/core_slim/updater.py
-------------------------
Auto-Updater für die Slim-App über GitHub-Releases.

Strategie (vs. Big-App-Updater): wir laden das vorgebaute Slim-ZIP aus
dem aktuellsten GitHub-Release. Vorteile gegenüber Branch-Zipball:
- klar versioniert (Tag aus VERSION)
- enthält genau die Slim-Files (kein Big-App-Müll)
- enthält Wheels in der passenden Version
- Größenvorteil: ~150 MB Asset statt ~50 MB Repo + manueller pip

Quelle: github.com/ahornhotels/Suite8XRechnung/releases
Asset-Konvention: `Suite8XRechnungSlim-X.Y.Z.zip`

State wird in `slim/data/update_state.json` persistiert.
"""
from __future__ import annotations

import io
import json
import logging
import re
import shutil
import subprocess
import tempfile
import zipfile
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
DEFAULT_REPO = "Suite8XRechnung"

# Pfade die beim Update NIE überschrieben werden — bleiben so wie sie sind
PRESERVE = {
    # Slim-spezifische Runtime + User-Configs
    "slim/config",
    "slim/data",
    "slim/logs",
    # Eingebautes Python mit installiertem oracledb/typing_extensions usw.
    # — wenn wir das überschreiben, ist die App nach Update kaputt bis pip
    # neu installiert wird. Embedded Python bleibt also unangetastet.
    "install/python",
    "install/jre",
    "install/wheels",
    "install/instantclient",
    "install/nssm.exe",
    # KoSIT-Material (groß, kommt selten neu)
    "validation",
    # Big-App-Verzeichnisse (sollten gar nicht im Slim-Pfad sein, aber
    # falls jemand das ZIP über eine Big-App entpackt: nicht anfassen)
    "config",
    "data",
    "logs",
    "api",
    "jobs",
    "frontend",
    "core",  # Big-App-Module — werden beim Update über die Slim-Files
             # NICHT aktualisiert; Slim teilt core/ aber das wird vom
             # Slim-ZIP mitgebracht. Die Slim-Variante überschreibt das.
    ".venv",
    ".git",
    ".pytest_cache",
    "__pycache__",
}

# Slim-relevante Pfade die SCHON beim Update aktualisiert werden müssen.
# Liste wird beim Update GEGEN PRESERVE geprüft: nur was hier drin ist UND
# nicht im PRESERVE, wird kopiert.
UPDATE_TARGETS = {
    "slim",
    "modules",
    "core",  # für Slim wird core/ überschrieben - sind dieselben Files
             # wie im Slim-ZIP, also kein Konflikt
    "sql",
    "templates",
    "scripts",
    "docs",
    "VERSION",
    "LICENSE",
    "README.md",
    "requirements.txt",
}

STATE_FILE = APP_ROOT / "slim" / "data" / "update_state.json"


class UpdateError(Exception):
    pass


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
        return {"last_version": None, "applied_at": None, "release_url": None}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("update_state.json beschaedigt: %s", e)
        return {"last_version": None, "applied_at": None, "release_url": None}


def save_state(data: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ─────────────────────────── Konfiguration ───────────────────────────

def load_update_config() -> dict:
    """Lädt slim/config/update.json, fügt Defaults hinzu. Token wird
    entschlüsselt wenn vorhanden.

    Default: Updates aktiviert, öffentliches Repo ahornhotels/Suite8XRechnung.
    Wer ein anderes Repo / privates Repo will: update.json anlegen.
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
        "User-Agent": "Suite8XRechnungSlim-Updater/1.0",
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


def find_slim_asset(release: dict) -> Optional[dict]:
    """Findet das Slim-ZIP-Asset im Release."""
    for a in release.get("assets", []):
        name = a.get("name", "")
        if name.startswith("Suite8XRechnungSlim-") and name.endswith(".zip"):
            return a
    return None


def check_for_update(cfg: Optional[dict] = None) -> dict:
    """Liefert {current_version, latest_version, available, release_url,
    release_notes, asset_size_mb, error?}.
    """
    if cfg is None:
        cfg = load_update_config()

    result = {
        "current_version": current_version(),
        "latest_version": None,
        "latest_tag": None,
        "release_url": None,
        "release_notes": None,
        "asset_name": None,
        "asset_size_mb": None,
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
    asset = find_slim_asset(release)
    if asset is None:
        result["error"] = (
            f"Release {tag} hat kein Slim-ZIP-Asset "
            "(erwartet: Suite8XRechnungSlim-X.Y.Z.zip)"
        )
        return result

    result["latest_tag"] = tag
    result["latest_version"] = tag.lstrip("vV")
    result["release_url"] = release.get("html_url")
    result["release_notes"] = (release.get("body") or "")[:2000]
    result["asset_name"] = asset.get("name")
    result["asset_size_mb"] = round(asset.get("size", 0) / (1024 * 1024), 1)
    result["asset_url"] = asset.get("browser_download_url")

    cur = _parse_version(result["current_version"])
    latest = _parse_version(result["latest_version"])
    result["available"] = latest > cur
    return result


# ─────────────────────────── Apply ───────────────────────────

def download_asset(url: str, cfg: dict) -> bytes:
    logger.info("Slim-ZIP-Download: %s", url)
    # Für browser_download_url braucht es application/octet-stream als Accept
    headers = _gh_headers(cfg, accept="application/octet-stream")
    try:
        resp = httpx.get(url, headers=headers, timeout=300.0,
                         follow_redirects=True)
    except httpx.HTTPError as e:
        raise UpdateError(f"Download fehlgeschlagen: {e}")
    if resp.status_code >= 400:
        raise UpdateError(f"Download HTTP {resp.status_code}")
    logger.info("Slim-ZIP geladen: %d Bytes", len(resp.content))
    return resp.content


def _path_in_preserve(rel_path: str) -> bool:
    """Prüft ob ein Pfad (relativ zum App-Root, Slash-separiert) in PRESERVE
    fällt. Vergleich auf Prefix-Match."""
    parts = rel_path.replace("\\", "/").split("/")
    for i in range(1, len(parts) + 1):
        prefix = "/".join(parts[:i])
        if prefix in PRESERVE:
            return True
    # Top-Level-Dir vs PRESERVE-Set
    return parts[0] in PRESERVE


def apply_update_from_zip(zip_bytes: bytes, dry_run: bool = False) -> dict:
    """Entpackt das Slim-ZIP, kopiert nur die Slim-relevanten Pfade nach
    APP_ROOT. PRESERVE wird GRANULAR durchgesetzt (auf Sub-Pfad-Ebene),
    damit z.B. ``slim/`` aktualisiert wird, aber ``slim/config/``,
    ``slim/data/`` und ``slim/logs/`` unangetastet bleiben.

    Strategie:
      - Iteriere File-für-File durch das entpackte ZIP
      - Pro Pfad: Top-Level in UPDATE_TARGETS? Nein -> ignorieren
      - Pfad in PRESERVE (granular, Prefix-Match)? Ja -> preserved
      - Sonst: kopieren (mit .new-Fallback bei Lock)

    Nachteil: gelöschte Files in der neuen Version bleiben am Server
    liegen. Für jetzt akzeptiert; bei Major-Releases lieber
    Vollinstallation aus dem ZIP.
    """
    with tempfile.TemporaryDirectory(prefix="slim_upd_") as tmp:
        tmp_path = Path(tmp)
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                zf.extractall(tmp_path)
        except zipfile.BadZipFile as e:
            raise UpdateError(f"Kein valides ZIP: {e}")

        # Slim-ZIP entpackt sich flach
        repo_root = tmp_path
        if not (repo_root / "slim" / "main_slim.py").exists():
            candidates = [p for p in tmp_path.iterdir()
                          if p.is_dir() and (p / "slim" / "main_slim.py").exists()]
            if candidates:
                repo_root = candidates[0]
            else:
                raise UpdateError(
                    "ZIP enthielt kein slim/main_slim.py - falscher Release?"
                )

        stats = {"copied": [], "preserved": [], "failed": [],
                 "dry_run": dry_run}

        for src in repo_root.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(repo_root).as_posix()
            top = rel.split("/", 1)[0]

            # Nur die markierten Top-Level-Pfade interessieren uns
            if top not in UPDATE_TARGETS:
                continue
            # Granular: PRESERVE-Liste (mit Sub-Pfaden) durchsetzen
            if _path_in_preserve(rel):
                stats["preserved"].append(rel)
                continue

            if dry_run:
                stats["copied"].append(rel)
                continue

            dst = APP_ROOT / rel
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    try:
                        dst.unlink()
                    except PermissionError:
                        # Datei gelockt (Service läuft, hat .py-File offen).
                        # Als .new ablegen — beim nächsten Service-Restart greift sie.
                        backup = dst.with_suffix(dst.suffix + ".new")
                        shutil.copy2(src, backup)
                        stats["failed"].append(f"{rel} (-> .new)")
                        continue
                shutil.copy2(src, dst)
                stats["copied"].append(rel)
            except Exception as e:
                logger.exception("Konnte %s nicht kopieren", rel)
                stats["failed"].append(f"{rel}: {e}")

        return stats


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


def perform_full_update(cfg: Optional[dict] = None) -> dict:
    """Check + Download + Apply + State + Restart in einem."""
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

    asset_url = check.get("asset_url")
    if not asset_url:
        raise UpdateError("Asset-URL fehlt in der Check-Antwort")

    zip_bytes = download_asset(asset_url, cfg)
    stats = apply_update_from_zip(zip_bytes)

    save_state({
        "last_version": check["latest_version"],
        "last_tag": check["latest_tag"],
        "release_url": check["release_url"],
        "applied_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })

    restart_service_detached()

    return {
        "applied": True,
        "from_version": check["current_version"],
        "to_version": check["latest_version"],
        "copied": stats["copied"],
        "preserved": stats["preserved"],
        "failed": stats["failed"],
        "message": "Update angewendet, Service startet in ~4 Sekunden neu.",
    }
