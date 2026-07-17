"""Tests fuer slim/core_slim/audit_jsonl."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from slim.core_slim import audit_jsonl


def _read_all(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_record_writes_single_line(tmp_path):
    audit_jsonl.record(tmp_path, "attach_ok", wmai_id=42,
                       zinv_number="144853", details={"sha256": "abc"})
    files = sorted(tmp_path.glob("audit-*.jsonl"))
    assert len(files) == 1
    entries = _read_all(files[0])
    assert len(entries) == 1
    e = entries[0]
    assert e["event"] == "attach_ok"
    assert e["wmai_id"] == 42
    assert e["zinv_number"] == "144853"
    assert e["details"] == {"sha256": "abc"}
    # PC-Zeit mit UTC-Offset statt "Z": 2026-07-17T11:54:48.123+02:00
    import re
    assert re.search(r"\.\d{3}[+-]\d{2}:\d{2}$", e["ts"]), e["ts"]
    # ts muss der lokalen Serverzeit entsprechen (nicht UTC verschoben)
    ts = datetime.fromisoformat(e["ts"])
    assert ts.utcoffset() == datetime.now().astimezone().utcoffset()


def test_record_appends_multiple(tmp_path):
    for i in range(5):
        audit_jsonl.record(tmp_path, "x", wmai_id=i)
    files = sorted(tmp_path.glob("audit-*.jsonl"))
    assert len(_read_all(files[0])) == 5


def test_record_safe_swallows_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_jsonl, "record",
                        lambda *a, **kw: (_ for _ in ()).throw(IOError("disk full")))
    # darf NICHT propagieren
    result = audit_jsonl.record_safe(tmp_path, "x")
    assert result is None


def test_truncate_details_keeps_small_payloads(tmp_path):
    small = {"a": "x" * 100}
    audit_jsonl.record(tmp_path, "x", details=small)
    files = sorted(tmp_path.glob("audit-*.jsonl"))
    e = _read_all(files[0])[0]
    assert e["details"] == small


def test_truncate_details_caps_huge_payloads(tmp_path):
    huge = {"a": "x" * 10000}
    audit_jsonl.record(tmp_path, "x", details=huge)
    files = sorted(tmp_path.glob("audit-*.jsonl"))
    e = _read_all(files[0])[0]
    assert isinstance(e["details"], dict)
    assert e["details"].get("truncated") is True


def test_tail_returns_last_n(tmp_path):
    for i in range(20):
        audit_jsonl.record(tmp_path, f"event_{i}")
    last = audit_jsonl.tail(tmp_path, n=5)
    assert len(last) == 5
    assert [e["event"] for e in last] == [f"event_{i}" for i in range(15, 20)]


def test_tail_handles_missing_file(tmp_path):
    assert audit_jsonl.tail(tmp_path, n=10) == []


def test_tail_skips_malformed_lines(tmp_path):
    audit_jsonl.record(tmp_path, "ok")
    f = sorted(tmp_path.glob("audit-*.jsonl"))[0]
    with open(f, "a", encoding="utf-8") as fh:
        fh.write("not json at all\n")
    audit_jsonl.record(tmp_path, "ok2")
    last = audit_jsonl.tail(tmp_path, n=10)
    assert [e["event"] for e in last] == ["ok", "ok2"]


def test_monthly_rotation_path_is_correct(tmp_path):
    target = datetime(2026, 1, 15, tzinfo=timezone.utc)
    p = audit_jsonl._audit_path(tmp_path, now=target)
    assert p.name == "audit-2026-01.jsonl"


def test_tail_reads_prev_month_when_current_short(tmp_path):
    # zwei Eintraege im Januar schreiben (kuenstlich via Path)
    jan_file = tmp_path / "audit-2025-12.jsonl"
    jan_file.write_text(
        '{"ts": "2025-12-31T23:00:00.000Z", "event": "old"}\n',
        encoding="utf-8",
    )
    # heutige Datei mit einem Eintrag
    audit_jsonl.record(tmp_path, "new")
    # tail mit Bezugsdatum Januar 2026 holt aus beiden Dateien
    target = datetime(2026, 1, 5, tzinfo=timezone.utc)
    entries = audit_jsonl.tail(tmp_path, n=10, now=target)
    events = [e["event"] for e in entries]
    assert "old" in events  # Vormonat wurde mitgelesen


def test_tail_returns_newest_when_capped(tmp_path):
    """Reihenfolge-Regression: tail muss neueste Eintraege liefern, nicht aelteste.

    Dateien direkt schreiben (statt record), damit der Test unabhaengig
    vom Echtzeit-Datum laeuft.
    """
    dec_file = tmp_path / "audit-2025-12.jsonl"
    dec_file.write_text(
        "\n".join(
            f'{{"ts": "2025-12-{d:02d}T12:00:00.000Z", "event": "dec_{d}"}}'
            for d in range(1, 6)
        ) + "\n",
        encoding="utf-8",
    )
    jan_file = tmp_path / "audit-2026-01.jsonl"
    jan_file.write_text(
        "\n".join(
            f'{{"ts": "2026-01-{d:02d}T12:00:00.000Z", "event": "jan_{d}"}}'
            for d in range(1, 6)
        ) + "\n",
        encoding="utf-8",
    )
    target = datetime(2026, 1, 10, tzinfo=timezone.utc)
    entries = audit_jsonl.tail(tmp_path, n=3, now=target)
    events = [e["event"] for e in entries]
    assert all(e.startswith("jan_") for e in events), \
        f"erwartete neueste jan-Eintraege, bekam: {events}"


def test_details_with_bytes_serialized_via_default_str(tmp_path):
    """bytes/datetime sollen via default=str konvertiert werden."""
    audit_jsonl.record(tmp_path, "x", details={"xml": b"<X/>",
                                                "when": datetime(2026, 6, 3)})
    files = sorted(tmp_path.glob("audit-*.jsonl"))
    e = _read_all(files[0])[0]
    # Beide Felder muessen als str gelandet sein (kein Crash, kein repr-Garbage)
    assert isinstance(e["details"]["xml"], str)
    assert "X" in e["details"]["xml"]
    assert isinstance(e["details"]["when"], str)
