"""Tests fuer slim/core_slim/clock.py — lokale PC-Zeit (offset-aware).

Design: docs/superpowers/specs/2026-07-03-betriebs-haertung-design.md, Punkt 3.
"""
from datetime import datetime

from slim.core_slim.clock import now_local


def test_now_local_ist_offset_aware():
    t = now_local()
    assert t.tzinfo is not None
    assert t.utcoffset() is not None


def test_now_local_entspricht_lokaler_systemzeit():
    t = now_local()
    assert t.utcoffset() == datetime.now().astimezone().utcoffset()
    # keine nennenswerte Abweichung zur Systemuhr
    delta = abs((datetime.now().astimezone() - t).total_seconds())
    assert delta < 5
