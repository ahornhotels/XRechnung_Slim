"""
core/logging_setup.py
---------------------
Tagliche Rotation, 30 Tage Aufbewahrung, Logs nach <root>/logs/app-YYYYMMDD.log.
Zusatzlich Console-Handler fuer stdout (uvicorn-Output).
"""
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class _SuppressWindowsProactorReset(logging.Filter):
    """Filtert ``ConnectionResetError [WinError 10054]`` aus asyncio-Logs.

    Bekanntes Windows-asyncio-Artefakt mit dem Proactor-Eventloop:
    sobald ein HTTP-Client (Browser, Reload-Skript) seine Verbindung
    abrupt schliesst, wirft asyncio im internen Cleanup einen
    ConnectionResetError. Funktional irrelevant — uvicorn hat die
    Antwort bereits gesendet — aber laut im Log.

    Wir schlucken nur exakt diese eine Exception-Variante. Andere
    asyncio-Fehler bleiben sichtbar.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "asyncio":
            return True
        exc = record.exc_info
        if exc and isinstance(exc[1], ConnectionResetError):
            return False
        if "WinError 10054" in str(record.getMessage()):
            return False
        return True


def setup_logging(level: str = "INFO") -> logging.Logger:
    """
    Initialisiert Root-Logger: taglich rotierende Datei + Console.
    Idempotent: mehrfacher Aufruf ersetzt bestehende Handler.

    Args:
        level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'

    Returns:
        Root-Logger
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()

    # Alte Handler entfernen (uvicorn --reload Schutz)
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = TimedRotatingFileHandler(
        filename=str(LOG_DIR / "app.log"),
        when="midnight",
        backupCount=30,
        encoding="utf-8",
        utc=False,
    )
    # Suffix fuer rotierte Files: app.log.2026-05-17
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    log_level = _LEVELS.get(level.upper(), logging.INFO)
    root.setLevel(log_level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # asyncio-Proactor-Reset-Filter auf beiden Handlern aktivieren
    _filter = _SuppressWindowsProactorReset()
    file_handler.addFilter(_filter)
    console_handler.addFilter(_filter)

    return root
