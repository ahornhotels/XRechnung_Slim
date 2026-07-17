"""
slim/core_slim/clock.py
-----------------------
Lokale Server-Zeit (PC-Zeit) als offset-aware datetime.

Audit-, Archiv- und Status-Zeitstempel zeigen dem Operator die PC-Zeit
statt UTC — der Offset bleibt erhalten, damit die Werte eindeutig und
maschinell parsebar bleiben (ISO8601, z. B. 2026-07-17T11:54:48+02:00).
"""
from datetime import datetime


def now_local() -> datetime:
    return datetime.now().astimezone()
