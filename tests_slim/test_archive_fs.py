"""Tests fuer slim/core_slim/archive_fs."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from slim.core_slim import archive_fs


def test_save_writes_xml_and_sha256(tmp_path):
    xml = b"<Invoice/>"
    r = archive_fs.save_xml(tmp_path, "144853", xml)
    xml_path = Path(r["xml_path"])
    assert xml_path.exists()
    assert xml_path.read_bytes() == xml
    assert r["sha256"] == hashlib.sha256(xml).hexdigest()

    sha_path = xml_path.parent / "144853.sha256"
    assert sha_path.exists()
    line = sha_path.read_text(encoding="utf-8").strip()
    assert line.startswith(r["sha256"])
    assert "144853.xml" in line


def test_save_creates_year_month_bucket(tmp_path):
    target = datetime(2026, 7, 1, tzinfo=timezone.utc)
    r = archive_fs.save_xml(tmp_path, "abc", b"<X/>", now=target)
    assert "/2026/07/" in r["xml_path"].replace("\\", "/")


def test_save_renames_existing_on_conflict(tmp_path):
    target = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
    a = archive_fs.save_xml(tmp_path, "144853", b"<v1/>", now=target)
    assert a["renamed_existing"] is None

    target2 = datetime(2026, 6, 3, 13, 0, 0, tzinfo=timezone.utc)
    b = archive_fs.save_xml(tmp_path, "144853", b"<v2/>", now=target2)
    assert b["renamed_existing"] is not None
    # v2 ist jetzt unter dem Hauptnamen
    assert Path(b["xml_path"]).read_bytes() == b"<v2/>"
    # v1 wurde versioniert weggespeichert
    assert Path(b["renamed_existing"]).read_bytes() == b"<v1/>"


def test_save_with_kosit_report(tmp_path):
    r = archive_fs.save_xml(
        tmp_path, "144853", b"<X/>", kosit_report=b"<report/>",
    )
    assert r["kosit_path"] is not None
    assert Path(r["kosit_path"]).read_bytes() == b"<report/>"


def test_safe_name_strips_path_separators():
    assert archive_fs._safe_name("a/b") == "a_b"
    assert archive_fs._safe_name("a\\b") == "a_b"
    assert archive_fs._safe_name("") == "unknown"
    assert archive_fs._safe_name("  ") == "unknown"


def test_safe_name_blocks_parent_dir_traversal():
    # `..` darf nicht als Dateiname stehenbleiben
    assert ".." not in archive_fs._safe_name("..")
    assert ".." not in archive_fs._safe_name("../etc/passwd")


def test_safe_name_blocks_windows_reserved():
    # CON/PRN/NUL etc. wuerden auf Windows beim open() crashen
    for reserved in ("CON", "PRN", "NUL", "AUX", "COM1", "LPT9", "con", "prn"):
        out = archive_fs._safe_name(reserved)
        assert out.upper() not in archive_fs._WINDOWS_RESERVED
        assert out.startswith("_")


def test_safe_name_strips_non_whitelist_chars():
    assert archive_fs._safe_name("AB#12$") == "AB_12_"
    # Unicode wird ebenfalls ersetzt
    assert "ä" not in archive_fs._safe_name("Hötel")


def test_safe_name_caps_length():
    long = "A" * 200
    out = archive_fs._safe_name(long)
    assert len(out) <= 64


def test_find_xml_returns_main_files(tmp_path):
    archive_fs.save_xml(tmp_path, "144853", b"<a/>",
                        now=datetime(2026, 6, 1, tzinfo=timezone.utc))
    archive_fs.save_xml(tmp_path, "144853", b"<b/>",
                        now=datetime(2026, 7, 1, tzinfo=timezone.utc))
    found = archive_fs.find_xml(tmp_path, "144853")
    assert len(found) == 2  # jeden Monat eine Hauptdatei
    # Sortiert: neueste zuerst (Juli > Juni alphanumerisch im Pfad)
    assert "07" in str(found[0])


def test_save_with_filename_uses_template_stem(tmp_path):
    xml = b"<Invoice/>"
    r = archive_fs.save_xml(
        tmp_path, "144853", xml,
        kosit_report=b"<report/>",
        filename="XRechnung_144853.xml",
    )
    xml_path = Path(r["xml_path"])
    assert xml_path.name == "XRechnung_144853.xml"
    # Seitendateien folgen demselben Stem
    assert (xml_path.parent / "XRechnung_144853.sha256").exists()
    assert Path(r["kosit_path"]).name == "XRechnung_144853.kosit-report.xml"
    # sha256sum-Zeile referenziert den Template-Namen
    line = (xml_path.parent / "XRechnung_144853.sha256").read_text(
        encoding="utf-8"
    ).strip()
    assert "XRechnung_144853.xml" in line


def test_save_with_filename_conflict_versioning(tmp_path):
    t1 = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 3, 13, 0, 0, tzinfo=timezone.utc)
    archive_fs.save_xml(tmp_path, "144853", b"<v1/>",
                        filename="XRechnung_144853.xml", now=t1)
    r = archive_fs.save_xml(tmp_path, "144853", b"<v2/>",
                            filename="XRechnung_144853.xml", now=t2)
    assert r["renamed_existing"] is not None
    assert "XRechnung_144853." in Path(r["renamed_existing"]).name
    assert Path(r["renamed_existing"]).read_bytes() == b"<v1/>"


def test_save_with_filename_sanitizes_bad_chars(tmp_path):
    r = archive_fs.save_xml(
        tmp_path, "144853", b"<X/>",
        filename="../bö$e/CON.xml",
    )
    name = Path(r["xml_path"]).name
    assert ".." not in name
    assert "/" not in name and "\\" not in name
    assert name.endswith(".xml")


def test_find_xml_matches_template_named_files(tmp_path):
    archive_fs.save_xml(
        tmp_path, "144853", b"<a/>",
        kosit_report=b"<report/>",
        filename="XRechnung_144853.xml",
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    found = archive_fs.find_xml(tmp_path, "144853")
    assert len(found) == 1
    assert found[0].name == "XRechnung_144853.xml"


def test_find_xml_excludes_kosit_reports_and_versions(tmp_path):
    t1 = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 3, 13, 0, 0, tzinfo=timezone.utc)
    archive_fs.save_xml(tmp_path, "144853", b"<v1/>",
                        kosit_report=b"<report/>",
                        filename="XRechnung_144853.xml", now=t1)
    archive_fs.save_xml(tmp_path, "144853", b"<v2/>",
                        kosit_report=b"<report/>",
                        filename="XRechnung_144853.xml", now=t2)
    found = archive_fs.find_xml(tmp_path, "144853")
    # Nur die Hauptdatei — keine .kosit-report.xml, keine .<ts>.xml-Version
    assert len(found) == 1
    assert found[0].read_bytes() == b"<v2/>"


# ------------------------------------------------ Fehler-XML-Ablage (invalid)

def test_save_invalid_writes_xml_and_error_txt(tmp_path):
    r = archive_fs.save_invalid_xml(
        tmp_path, "48400", b"<CreditNote/>",
        event="validator_fail", error_text="BG-3 fehlt",
    )
    xml_path = Path(r["xml_path"])
    assert xml_path.exists()
    assert xml_path.read_bytes() == b"<CreditNote/>"

    err_path = Path(r["error_path"])
    assert err_path.exists()
    text = err_path.read_text(encoding="utf-8")
    assert "validator_fail" in text
    assert "BG-3 fehlt" in text


def test_save_invalid_uses_year_month_bucket_under_xml_invalid(tmp_path):
    target = datetime(2026, 7, 1, tzinfo=timezone.utc)
    r = archive_fs.save_invalid_xml(
        tmp_path, "abc", b"<X/>",
        event="kosit_fail", error_text="BR-DE-5", now=target,
    )
    p = r["xml_path"].replace("\\", "/")
    assert "/xml_invalid/2026/07/" in p


def test_save_invalid_stays_out_of_valid_archive(tmp_path):
    """Fehler-XMLs duerfen die Erfolgs-Archivsuche nicht verunreinigen."""
    archive_fs.save_invalid_xml(
        tmp_path, "48400", b"<bad/>",
        event="validator_fail", error_text="x",
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    # find_xml sucht nur unter <data_dir>/xml — nichts darf auftauchen
    assert archive_fs.find_xml(tmp_path, "48400") == []
    assert not (tmp_path / "xml").exists()


def test_save_invalid_conflict_versioning(tmp_path):
    t1 = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 3, 13, 0, 0, tzinfo=timezone.utc)
    archive_fs.save_invalid_xml(tmp_path, "48400", b"<v1/>",
                                event="validator_fail", error_text="a", now=t1)
    r = archive_fs.save_invalid_xml(tmp_path, "48400", b"<v2/>",
                                    event="validator_fail", error_text="b", now=t2)
    assert r["renamed_existing"] is not None
    assert Path(r["xml_path"]).read_bytes() == b"<v2/>"
    assert Path(r["renamed_existing"]).read_bytes() == b"<v1/>"


def test_delete_invalid_removes_xml_and_error(tmp_path):
    archive_fs.save_invalid_xml(
        tmp_path, "48400", b"<bad/>",
        event="validator_fail", error_text="x",
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    removed = archive_fs.delete_invalid(tmp_path, "48400")
    assert removed >= 1
    # Kein Rest im xml_invalid-Baum
    leftovers = list((tmp_path / "xml_invalid").rglob("*48400*"))
    assert leftovers == []


def test_delete_invalid_noop_when_absent(tmp_path):
    # Darf nicht crashen, wenn es nie eine Fehler-XML gab
    assert archive_fs.delete_invalid(tmp_path, "nie-dagewesen") == 0
