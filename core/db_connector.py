"""
core/db_connector.py
--------------------
Oracle-Verbindung via oracledb Thick-Mode (lokaler Oracle Client).
Connection-Pool fuer FastAPI mit Lifecycle-Management.
"""
import logging
import os
from pathlib import Path
from typing import Optional

import oracledb

import core.config_loader as _cl
from core.crypto import load_key, decrypt

logger = logging.getLogger(__name__)

_pool: Optional[oracledb.ConnectionPool] = None
_thick_initialized: bool = False

# Typische Oracle-Client-Install-Roots auf Windows. Hier suchen wir
# nach tnsnames.ora wenn der User keinen TNS_ADMIN-Pfad konfiguriert hat.
_AUTO_TNS_SEARCH_ROOTS = [
    Path(r"C:\ORACLE"),
    Path(r"C:\oracle"),
    Path(r"C:\Program Files\Oracle"),
    Path(r"C:\app"),
]

# Mitgelieferter Oracle Instant Client (in install/instantclient/).
# Wird zur Loesung von DPY-3015 / Verifier-Inkompatibilitaeten
# automatisch verwendet, sobald `oci.dll` an dieser Stelle liegt.
_BUNDLED_INSTANT_CLIENT = (
    Path(__file__).resolve().parent.parent / "install" / "instantclient"
)


def _bundled_client_lib_dir() -> Optional[str]:
    """Pruft, ob ein mitgelieferter Instant Client neben dem App-Verzeichnis
    liegt. Returns: Pfad als string oder None."""
    if (_BUNDLED_INSTANT_CLIENT / "oci.dll").exists():
        return str(_BUNDLED_INSTANT_CLIENT)
    return None


def _auto_detect_tns_admin() -> Optional[str]:
    """Sucht nach tnsnames.ora in typischen Oracle-Client-Pfaden.
    Returns Pfad zum Verzeichnis (ohne Datei) oder None.
    Bevorzugt neuere Client-Versionen (sortiert reverse).
    """
    for root in _AUTO_TNS_SEARCH_ROOTS:
        if not root.exists():
            continue
        try:
            candidates = sorted(
                root.rglob("network/admin/tnsnames.ora"),
                key=lambda p: str(p),
                reverse=True,
            )
        except PermissionError:
            continue
        for cand in candidates:
            if cand.is_file():
                logger.info("Auto-detected TNS_ADMIN: %s", cand.parent)
                return str(cand.parent)
    return None


def init_pool() -> oracledb.ConnectionPool:
    """Erstellt Oracle Connection Pool. Initialisiert Thick-Client einmalig."""
    global _pool, _thick_initialized
    if _pool is not None:
        return _pool

    cfg = _cl.load_connection_config()
    key_path = _cl.CONFIG_DIR / "connection.key"
    key = load_key(key_path)
    password = decrypt(cfg["password"], key)

    # Thick-Mode-Aktivierung: explizit konfigurierter Pfad hat Vorrang,
    # sonst mitgelieferter Instant Client unter install/instantclient/.
    # Thick-Mode wird gebraucht fuer Oracle 21c-Datenbanken mit neueren
    # Password-Verifiern, die der Thin-Mode nicht unterstuetzt (DPY-3015).
    client_lib_dir = cfg.get("oracle_client_lib_dir") or _bundled_client_lib_dir()
    if not _thick_initialized and client_lib_dir:
        try:
            oracledb.init_oracle_client(lib_dir=client_lib_dir)
            _thick_initialized = True
            logger.info("Oracle Thick-Mode aktiviert (lib_dir=%s)", client_lib_dir)
        except oracledb.ProgrammingError:
            # Bereits initialisiert (z.B. in Tests)
            _thick_initialized = True
        except oracledb.DatabaseError as e:
            # Client-Bibliothek inkompatibel (z.B. 32-bit Client + 64-bit Python).
            # Thin-Mode wird automatisch verwendet.
            logger.warning(
                "Thick-Mode-Init fehlgeschlagen (%s) — falle auf Thin-Mode zurueck", e,
            )
            _thick_initialized = True

    pool_kwargs: dict = dict(
        user=cfg["username"],
        password=password,
        dsn=cfg["tns_alias"],
        min=1, max=4, increment=1,
    )
    tns_admin = cfg.get("tns_admin") or _auto_detect_tns_admin()
    if tns_admin:
        # Thick-Mode: TNS_ADMIN Umgebungsvariable (wird vom Oracle Client gelesen).
        # Thin-Mode: config_dir Parameter fuer tnsnames.ora-Aufloesung.
        os.environ["TNS_ADMIN"] = tns_admin
        pool_kwargs["config_dir"] = tns_admin

    _pool = oracledb.create_pool(**pool_kwargs)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        except oracledb.Error:
            pass
        _pool = None


def get_connection():
    """Akquiriert Connection aus Pool. Als Context-Manager nutzbar."""
    return init_pool().acquire()


def test_connection() -> dict:
    """SELECT 1-Test. Gibt {db_name, user} zurueck. Wirft Exception bei Fehler."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT SYS_CONTEXT('USERENV','DB_NAME'), USER FROM dual")
        db_name, user = cur.fetchone()
        return {"db_name": db_name, "user": user}
