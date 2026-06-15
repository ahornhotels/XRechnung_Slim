"""Tests fuer slim/core_slim/sql_overrides.py - Validierung + Load/Save/Delete."""
import pytest
from pathlib import Path

from slim.core_slim import sql_overrides


# ─────────────── Validierung ───────────────

def test_valid_select_with_bindvar_ok():
    sql = "SELECT * FROM zinv WHERE zinv_id = :zinv_id"
    sql_overrides.validate(sql, "invoice_header.sql")  # darf NICHT werfen


def test_valid_with_cte_ok():
    sql = "WITH x AS (SELECT 1 FROM dual) SELECT * FROM x WHERE :zinv_id = :zinv_id"
    sql_overrides.validate(sql, "invoice_header.sql")


def test_invalid_empty_raises():
    with pytest.raises(sql_overrides.SqlValidationError, match="Leer"):
        sql_overrides.validate("", "invoice_header.sql")


def test_invalid_too_long_raises():
    sql = "SELECT :zinv_id, " + "a," * 30_000 + "1 FROM dual"
    with pytest.raises(sql_overrides.SqlValidationError, match="zu lang"):
        sql_overrides.validate(sql, "invoice_header.sql")


def test_invalid_non_select_raises():
    with pytest.raises(sql_overrides.SqlValidationError, match="SELECT oder WITH"):
        sql_overrides.validate(
            "UPDATE zinv SET zinv_total=0 WHERE :zinv_id=:zinv_id",
            "invoice_header.sql",
        )


def test_forbidden_keyword_in_second_statement():
    """Zwei Statements mit Semikolon: das zweite darf kein DDL/DML sein."""
    sql = ("SELECT * FROM zinv WHERE zinv_id = :zinv_id; "
           "DROP TABLE zinv")
    with pytest.raises(sql_overrides.SqlValidationError, match="DROP"):
        sql_overrides.validate(sql, "invoice_header.sql")


def test_forbidden_in_subquery_raises():
    """DELETE als Subquery-Trick - wird auch erkannt."""
    sql = "SELECT * FROM (DELETE FROM zinv WHERE :zinv_id=:zinv_id)"
    # startet zwar mit SELECT, aber DELETE im Body wird gefunden
    with pytest.raises(sql_overrides.SqlValidationError, match="DELETE"):
        sql_overrides.validate(sql, "invoice_header.sql")


def test_keyword_in_comment_is_ok():
    """Verbotene Keywords IN KOMMENTAREN sind harmlos und werden ignoriert."""
    sql = "-- DROP TABLE wuerde hier nichts tun\nSELECT * FROM zinv WHERE zinv_id = :zinv_id"
    sql_overrides.validate(sql, "invoice_header.sql")  # darf NICHT werfen


def test_keyword_in_block_comment_is_ok():
    sql = "/* DROP TABLE */ SELECT * FROM zinv WHERE zinv_id = :zinv_id"
    sql_overrides.validate(sql, "invoice_header.sql")


def test_substring_match_doesnt_trigger():
    """'CREATEDATE' enthaelt 'CREATE' als Substring, ist aber harmlos.
    Whole-word-Match muss greifen."""
    sql = "SELECT createdate FROM zinv WHERE zinv_id = :zinv_id"
    sql_overrides.validate(sql, "invoice_header.sql")  # darf NICHT werfen


def test_missing_bindvar_raises():
    sql = "SELECT * FROM zinv WHERE zinv_id = 12345"
    with pytest.raises(sql_overrides.SqlValidationError, match=":zinv_id"):
        sql_overrides.validate(sql, "invoice_header.sql")


def test_invoice_list_uses_days_bindvar():
    """invoice_list.sql hat eine andere Bindvariable als die anderen."""
    sql = "SELECT * FROM zinv WHERE zinv_date >= sysdate - :days"
    sql_overrides.validate(sql, "invoice_list.sql")  # OK
    # mit :zinv_id stattdessen muesste es failen
    with pytest.raises(sql_overrides.SqlValidationError, match=":days"):
        sql_overrides.validate(
            "SELECT * FROM zinv WHERE zinv_id = :zinv_id",
            "invoice_list.sql",
        )


def test_unknown_template_name_rejected():
    with pytest.raises(sql_overrides.SqlValidationError, match="nicht erlaubt"):
        sql_overrides.validate(
            "SELECT :zinv_id FROM dual", "etc_passwd.sql",
        )


# ─────────────── Filesystem (load/save/delete/list) ───────────────

def test_save_and_load(tmp_path):
    sql = "SELECT * FROM zinv WHERE zinv_id = :zinv_id"
    sql_overrides.save(tmp_path, "invoice_header.sql", sql)
    assert sql_overrides.load(tmp_path, "invoice_header.sql") == sql


def test_load_returns_none_when_no_override(tmp_path):
    assert sql_overrides.load(tmp_path, "invoice_header.sql") is None


def test_save_validates_before_writing(tmp_path):
    """Verbotenes SQL darf NICHT auf dem Filesystem landen."""
    with pytest.raises(sql_overrides.SqlValidationError):
        sql_overrides.save(tmp_path, "invoice_header.sql",
                           "DROP TABLE zinv")
    assert not (tmp_path / "sql_overrides" / "invoice_header.sql").exists()


def test_delete(tmp_path):
    sql_overrides.save(tmp_path, "invoice_lines.sql",
                        "SELECT :zinv_id FROM dual")
    assert sql_overrides.delete(tmp_path, "invoice_lines.sql") is True
    assert sql_overrides.delete(tmp_path, "invoice_lines.sql") is False  # idempotent
    assert sql_overrides.load(tmp_path, "invoice_lines.sql") is None


def test_list_overrides(tmp_path):
    assert sql_overrides.list_overrides(tmp_path) == []
    sql_overrides.save(tmp_path, "invoice_header.sql",
                        "SELECT :zinv_id FROM dual")
    sql_overrides.save(tmp_path, "invoice_tax.sql",
                        "SELECT :zinv_id FROM dual")
    assert set(sql_overrides.list_overrides(tmp_path)) == {
        "invoice_header.sql", "invoice_tax.sql",
    }


def test_list_overrides_ignores_unknown_files(tmp_path):
    """Manuell in das Verzeichnis gelegte Junk-Files werden ignoriert."""
    root = tmp_path / "sql_overrides"
    root.mkdir(parents=True)
    (root / "etc_passwd.sql").write_text("nope", encoding="utf-8")
    (root / "invoice_header.sql").write_text(
        "SELECT :zinv_id FROM dual", encoding="utf-8")
    assert sql_overrides.list_overrides(tmp_path) == ["invoice_header.sql"]


# ─────────────── Poller-Integration ───────────────

def test_invoice_fetcher_uses_override_when_present(tmp_path, monkeypatch):
    """Wenn ein Override im data_dir liegt, MUSS _read_sql ihn nehmen."""
    # 1) CONFIG_DIR auf <tmp>/config umlenken, data_dir wird <tmp>/data
    cfg_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    cfg_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setenv("SUITE8_CONFIG_DIR", str(cfg_dir))

    import importlib
    import core.config_loader as cl
    importlib.reload(cl)
    from modules import invoice_fetcher
    importlib.reload(invoice_fetcher)

    # 2) Override anlegen — verwende eine eindeutige Marker-Zeile
    marker = "-- OVERRIDE-MARKER 42\nSELECT :zinv_id FROM dual"
    (data_dir / "sql_overrides").mkdir()
    (data_dir / "sql_overrides" / "invoice_header.sql").write_text(
        marker, encoding="utf-8",
    )

    # 3) _read_sql muss den Override liefern, nicht das Repo-File
    out = invoice_fetcher._read_sql("invoice_header.sql")
    assert "OVERRIDE-MARKER 42" in out


def test_invoice_fetcher_falls_back_to_repo_when_no_override(tmp_path, monkeypatch):
    """Ohne Override -> Repo-File aus sql/. Smoke: gibt's was und enthaelt
    den Bindvar."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    monkeypatch.setenv("SUITE8_CONFIG_DIR", str(cfg_dir))

    import importlib
    import core.config_loader as cl
    importlib.reload(cl)
    from modules import invoice_fetcher
    importlib.reload(invoice_fetcher)

    out = invoice_fetcher._read_sql("invoice_header.sql")
    assert ":zinv_id" in out
    assert "OVERRIDE-MARKER" not in out
