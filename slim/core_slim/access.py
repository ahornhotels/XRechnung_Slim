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
            elif ip == ipaddress.ip_address(entry):
                return True
        except ValueError:
            logger.debug("allowed_ips: Eintrag uebersprungen: %r", entry)
            continue
    return False


async def dispatch(request, call_next, allowed):
    """HTTP-Middleware-Dispatch: blockt nicht erlaubte Client-IPs mit 403."""
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client else None
    if not is_ip_allowed(host, allowed):
        logger.warning("Zugriff von %s geblockt (allowed_ips)", host)
        return JSONResponse(
            status_code=403,
            content={"detail": f"Zugriff von {host} nicht erlaubt"},
        )
    return await call_next(request)
