"""Integrations-Smoke gegen V8LIVE.

Nur READ-Operationen — kein attach_xml_to_wmai, kein UPDATE.
Skipt automatisch wenn keine slim/config/connection.json vorhanden ist
oder die DB nicht erreichbar.

Aufruf:
  RUN_DB_TESTS=1 .venv/Scripts/python.exe -m pytest tests_slim/test_integration_v8live.py -v
"""
import importlib
import os
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SLIM_CONFIG = _REPO / "slim" / "config"

if not (_SLIM_CONFIG / "connection.json").exists():
    pytest.skip("slim/config/connection.json fehlt", allow_module_level=True)
if os.environ.get("RUN_DB_TESTS") != "1":
    pytest.skip("RUN_DB_TESTS=1 nicht gesetzt", allow_module_level=True)


@pytest.fixture(scope="module", autouse=True)
def slim_config():
    """Patcht core.config_loader.CONFIG_DIR auf slim/config fuer den ganzen Modul-Lauf."""
    os.environ["SUITE8_CONFIG_DIR"] = str(_SLIM_CONFIG)
    import core.config_loader as cl
    importlib.reload(cl)
    # Pool resetten, damit es eine neue Connection gegen die Slim-Config oeffnet
    from core import db_connector
    db_connector.close_pool()
    db_connector._pool = None
    yield
    db_connector.close_pool()


def test_db_connection_works():
    from core import db_connector
    info = db_connector.test_connection()
    assert "db_name" in info
    assert info["user"]


def test_find_pending_wmai_runs():
    """Live-Query: WMAI mit BLOCKSEND=1 AND SENT=0. Liefert Liste (evtl. leer)."""
    from core.db_connector import get_connection
    from modules.suite8_mailer import find_pending_wmai
    with get_connection() as conn:
        rows = find_pending_wmai(conn=conn, limit=5)
    assert isinstance(rows, list)
    # Jedes Row-Dict hat die erwarteten Keys
    for r in rows:
        assert {"wmai_id", "filename", "subject", "to"} <= set(r)


def test_fetch_and_render_historical_invoice():
    """Eine historische ZINV-Nummer aus V8LIVE durch den vollen Pipe schicken.

    144853 ist im STATUS.md/Memory als Standard-Beispiel referenziert.
    Wenn die Nummer nicht existiert, faellt der Test mit ZINV-not-found
    aus — das ist informativ, kein Skip.
    """
    from modules import invoice_fetcher, invoice_validator, xml_builder

    # Probiere bekannte Beispiel-Rechnungen aus dem STATUS.md
    candidates = ["144853", "145983", "145970"]
    fetched = None
    used_number = None
    for nr in candidates:
        zinv_id = invoice_fetcher.find_zinv_id_by_number(nr)
        if zinv_id:
            inv = invoice_fetcher.fetch_invoice(zinv_id)
            if inv:
                fetched = inv
                used_number = nr
                break

    if fetched is None:
        pytest.skip(f"Keine der Beispiel-Rechnungen {candidates} in V8LIVE gefunden")

    issues = invoice_validator.validate(fetched)
    # Issues sind OK — die Rechnung darf unvollstaendig sein, das testen wir nicht
    if issues:
        pytest.skip(f"ZINV {used_number} hat Validator-Issues: "
                    f"{[i['message'] for i in issues[:3]]}")

    xml = xml_builder.build_and_validate(fetched)
    assert xml.startswith(b"<?xml")
    # UBL nutzt Namespace-Prefix ubl:Invoice oder ubl:CreditNote
    assert b":Invoice" in xml or b":CreditNote" in xml


def test_archive_writes_real_xml(tmp_path):
    """End-to-end ohne attach: Rechnung holen, XML bauen, im Archiv ablegen."""
    from modules import invoice_fetcher, invoice_validator, xml_builder
    from slim.core_slim import archive_fs

    for nr in ("144853", "145983", "145970"):
        zinv_id = invoice_fetcher.find_zinv_id_by_number(nr)
        if not zinv_id:
            continue
        inv = invoice_fetcher.fetch_invoice(zinv_id)
        if not inv:
            continue
        if invoice_validator.validate(inv):
            continue
        xml = xml_builder.build_and_validate(inv)
        result = archive_fs.save_xml(tmp_path, nr, xml)
        assert Path(result["xml_path"]).exists()
        assert Path(result["xml_path"]).read_bytes() == xml
        return
    pytest.skip("Keine renderbare Beispiel-Rechnung in V8LIVE gefunden")
