"""Tests fuer slim/core_slim/access.py — IP-Allowlist fuer Netzwerk-Zugriff.

Design: docs/superpowers/specs/2026-07-03-betriebs-haertung-design.md, Punkt 2.
localhost ist immer erlaubt; sonst entscheidet die konfigurierte Liste aus
exakten IPs und CIDR-Ranges. Fail-safe: leere/ungueltige Konfig -> nur localhost.
"""
from types import SimpleNamespace

import pytest

from slim.core_slim.access import dispatch, is_ip_allowed, lan_exposure_warning


# ─────────────── is_ip_allowed (reine Funktion) ───────────────

def test_localhost_immer_erlaubt_auch_bei_leerer_liste():
    assert is_ip_allowed("127.0.0.1", []) is True
    assert is_ip_allowed("::1", []) is True


def test_exakte_ip_treffer_und_fehltreffer():
    allowed = ["192.168.10.20"]
    assert is_ip_allowed("192.168.10.20", allowed) is True
    assert is_ip_allowed("192.168.10.21", allowed) is False


def test_cidr_range_treffer_und_fehltreffer():
    allowed = ["192.168.10.0/24"]
    assert is_ip_allowed("192.168.10.99", allowed) is True
    assert is_ip_allowed("192.168.11.99", allowed) is False


def test_leere_liste_blockt_fremde_ip():
    assert is_ip_allowed("10.0.0.5", []) is False


def test_ungueltige_eintraege_werden_uebersprungen():
    allowed = ["not-an-ip", "", "192.168.10.0/24"]
    assert is_ip_allowed("192.168.10.5", allowed) is True
    assert is_ip_allowed("10.0.0.5", allowed) is False


def test_ungueltige_client_ip_wird_geblockt():
    assert is_ip_allowed("testclient", ["192.168.10.0/24"]) is False
    assert is_ip_allowed("", ["192.168.10.0/24"]) is False


def test_ipv6_mapped_ipv4_wird_normalisiert():
    assert is_ip_allowed("::ffff:192.168.10.5", ["192.168.10.0/24"]) is True
    assert is_ip_allowed("::ffff:127.0.0.1", []) is True


def test_allowlist_eintrag_ipv6_mapped_matcht_ipv4_client():
    # Ein Allowlist-Eintrag in IPv6-mapped-Form muss den (normalisierten)
    # IPv4-Client treffen — sonst blockt ein aus einem Log kopierter Eintrag.
    assert is_ip_allowed("192.168.10.5", ["::ffff:192.168.10.5"]) is True
    assert is_ip_allowed("192.168.10.6", ["::ffff:192.168.10.5"]) is False


def test_lan_exposure_warning():
    # Bind ans Netz ohne Allowlist -> Warnung; sonst None.
    assert lan_exposure_warning("0.0.0.0", []) is not None
    assert lan_exposure_warning("192.168.1.10", []) is not None
    assert lan_exposure_warning("0.0.0.0", ["192.168.1.0/24"]) is None
    assert lan_exposure_warning("127.0.0.1", []) is None
    assert lan_exposure_warning("::1", []) is None
    assert lan_exposure_warning("localhost", []) is None


# ─────────────── dispatch (HTTP-Middleware) ───────────────

def _request(host, path="/api/status"):
    client = SimpleNamespace(host=host) if host is not None else None
    return SimpleNamespace(client=client, url=SimpleNamespace(path=path))


async def _call_next(request):
    return "OK-RESPONSE"


@pytest.mark.asyncio
async def test_dispatch_erlaubte_ip_durchgereicht():
    resp = await dispatch(_request("127.0.0.1"), _call_next, [])
    assert resp == "OK-RESPONSE"


@pytest.mark.asyncio
async def test_dispatch_geblockte_ip_403():
    resp = await dispatch(_request("10.0.0.5"), _call_next, [])
    assert resp.status_code == 403
    assert b"10.0.0.5" in resp.body


@pytest.mark.asyncio
async def test_dispatch_ohne_client_403():
    resp = await dispatch(_request(None), _call_next, [])
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_dispatch_allowlist_ip_erlaubt():
    resp = await dispatch(_request("192.168.10.5"), _call_next,
                          ["192.168.10.0/24"])
    assert resp == "OK-RESPONSE"


@pytest.mark.asyncio
async def test_dispatch_healthz_immer_erlaubt():
    # Monitoring-Endpoint bleibt auch fuer geblockte IPs erreichbar.
    resp = await dispatch(_request("10.0.0.5", path="/healthz"), _call_next, [])
    assert resp == "OK-RESPONSE"
