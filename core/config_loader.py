"""
core/config_loader.py
---------------------
Zentraler JSON-Konfigurationszugriff. Liest/schreibt alle config/*.json Dateien.
"""
import json
import os
from pathlib import Path

# Standard: <repo>/config. Slim-Variante / Tests koennen via Env-Var ueberschreiben.
CONFIG_DIR = Path(
    os.environ.get("SUITE8_CONFIG_DIR")
    or Path(__file__).resolve().parent.parent / "config"
)

DEFAULT_APP_SETTINGS = {
    "host": "127.0.0.1",
    "port": 8021,
    "log_level": "INFO",
    "list_window_days": 7,
    "retry_intervals_minutes": [5, 15, 60, 240, 1440],
    "max_retries": 5,
    "backup_time": "02:00",
    "backup_retention_days": 90,
    "kosit_validation": True,
    "xrechnung_version": "3.0.2",
    "update_check_time": "04:00",
}


def load_json(path: Path, default=None):
    """Liest eine JSON-Datei; gibt default zurueck wenn nicht vorhanden."""
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    """Schreibt ein Dict als formatiertes JSON nach <path>."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_app_settings() -> dict:
    """Laedt config/app_settings.json, ergaenzt fehlende Felder durch Defaults."""
    settings = load_json(CONFIG_DIR / "app_settings.json", default={})
    merged = {**DEFAULT_APP_SETTINGS, **settings}
    return merged


def load_hotel_config() -> dict:
    """Laedt config/hotel.json. Wirft FileNotFoundError wenn fehlend."""
    cfg = load_json(CONFIG_DIR / "hotel.json")
    if cfg is None:
        raise FileNotFoundError(
            "config/hotel.json fehlt. Setup-Wizard ausfuehren."
        )
    # Mail-Strategie + Suite8-WMAI-Anhang Defaults.
    # Pattern-Hintergrund: Suite8 schreibt im PDF-Filename die ZINV_ID
    # (interner PK), im Subject (wenn der Mail-Template das traegt) die
    # ZINV_NUMBER (Rechnungs-Folio-Nummer, fuer den Kunden sichtbar).
    # Default ist deshalb Subject-Pattern mit `(?P<zinv_number>...)` —
    # passt zu Hotel-Templates, die "Rechnung Nr. <N>" o.ae. nutzen.
    # Hotels mit anderem Subject-Format aendern das Pattern im UI.
    cfg.setdefault("mail_strategy", "graph")  # Bestandsinstallationen: kein Verhaltenswechsel
    cfg.setdefault("suite8_recognize_filename_pattern", "")
    cfg.setdefault(
        "suite8_recognize_subject_pattern",
        r"Rechnung\s+Nr\.?\s*(?P<zinv_number>\d+)",
    )
    cfg.setdefault("suite8_poll_interval_seconds", 30)
    cfg.setdefault("suite8_attachment_name_template", "{zinv_number}.xml")
    return cfg


def load_connection_config() -> dict:
    """Laedt config/connection.json. Wirft FileNotFoundError wenn fehlend."""
    cfg = load_json(CONFIG_DIR / "connection.json")
    if cfg is None:
        raise FileNotFoundError(
            "config/connection.json fehlt. Setup-Wizard ausfuehren."
        )
    return cfg
