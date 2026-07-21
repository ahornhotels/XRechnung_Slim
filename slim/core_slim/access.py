"""
slim/core_slim/access.py
------------------------
IP-Allowlist fuer den Netzwerk-Zugriff auf die Slim-App.

Die App hat kein Login. Wird sie per ``host: 0.0.0.0`` ins LAN geoeffnet,
beschraenkt diese Middleware den Zugriff auf konfigurierte Adressen
(``allowed_ips`` in app_settings.json: exakte IPv4/IPv6-Adressen oder
CIDR-Ranges). localhost ist immer erlaubt — leere oder fehlende Liste
bedeutet damit fail-safe: effektiv nur localhost.
"""
import ipaddress
import logging

from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Pfade, die immer erreichbar bleiben (Monitoring), auch fuer nicht
# gelistete IPs — der Health-Check verraet nichts Sensibles.
_EXEMPT_PATHS = frozenset({"/healthz"})

# Als "nur lokal" geltende host-Werte (kein Netzwerk-Bind).
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", ""})


def _parse_ip(value):
    """IP parsen; IPv6-mapped IPv4 (::ffff:a.b.c.d) auf IPv4 normalisieren.
    None bei ungueltigem Wert (z. B. Hostname) — defensiv, kein Crash."""
    try:
        ip = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped
    return ip


def is_ip_allowed(client_ip: str, allowed: list) -> bool:
    """True wenn ``client_ip`` localhost ist oder in ``allowed`` steht
    (exakte Adresse oder CIDR-Range). Ungueltige Eintraege werden
    uebersprungen; ungueltige Client-IP wird geblockt."""
    ip = _parse_ip(client_ip)
    if ip is None:
        return False
    if ip.is_loopback:
        return True
    for entry in allowed or []:
        entry = str(entry or "").strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                if ip in ipaddress.ip_network(entry, strict=False):
                    return True
            else:
                # Eintrag ebenfalls normalisieren (IPv6-mapped -> IPv4),
                # sonst matcht ein ::ffff:-Eintrag nie die IPv4-Client-IP.
                entry_ip = _parse_ip(entry)
                if entry_ip is not None and ip == entry_ip:
                    return True
        except ValueError:
            logger.debug("allowed_ips: Eintrag uebersprungen: %r", entry)
            continue
    return False


def lan_exposure_warning(host, allowed) -> str | None:
    """Warntext, wenn der Dienst ans Netzwerk bindet (host != localhost), die
    Allowlist aber leer ist — dann hat effektiv nur localhost Zugriff. Sonst
    None. Reine Funktion fuer den Startup-Check in main_slim."""
    if str(host or "").strip() in _LOCAL_HOSTS:
        return None
    if allowed:
        return None
    return (
        f"host={host} bindet ans Netzwerk, aber allowed_ips ist leer — "
        "es hat effektiv nur localhost Zugriff. In app_settings.json "
        "'allowed_ips' (IPs/CIDR) setzen und den Dienst neu starten."
    )


async def dispatch(request, call_next, allowed):
    """HTTP-Middleware-Dispatch: blockt nicht erlaubte Client-IPs mit 403.
    Monitoring-Pfade (``_EXEMPT_PATHS``) bleiben immer erreichbar."""
    path = getattr(getattr(request, "url", None), "path", "") or ""
    if path in _EXEMPT_PATHS:
        return await call_next(request)
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client else None
    if not is_ip_allowed(host, allowed):
        logger.warning("Zugriff von %s geblockt (allowed_ips)", host)
        return JSONResponse(
            status_code=403,
            content={"detail": f"Zugriff von {host} nicht erlaubt"},
        )
    return await call_next(request)
