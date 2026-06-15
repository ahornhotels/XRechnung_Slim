"""
modules/suite8_mailer.py
------------------------
DB-Schreibzugriff fuer den Suite8-WMAI-Anhang-Workflow.

Atomarer Insert XRechnung-XML als zweiter Anhang an eine bereits
vorbereitete WMAI-Mail in Suite8:
  1) INSERT WTXT (WTXT_DATA=BLOB, DOCFORMAT=6, COMPRESSED=0)
  2) INSERT WMAA (WMAA_WMAI_ID, WMAA_ATTACHMENT_WTXT_ID, WMAA_FILENAME)
  3) UPDATE WMAI SET WMAI_BLOCKSEND=0
     WHERE WMAI_ID=:id AND WMAI_BLOCKSEND=1 AND WMAI_SENT=0

Alle drei in EINER Transaktion. Rollback bei jedem Fehler.
"""
import logging

from core.db_connector import get_connection

logger = logging.getLogger(__name__)

WMAA_FILENAME_MAX = 128


def attach_xml_to_wmai(
    wmai_id: int,
    xml_bytes: bytes,
    filename: str,
    conn,
) -> dict:
    """Atomar XML-Anhang an eine BLOCKSEND=1-Mail haengen.

    Args:
        wmai_id: ID der bereits vorbereiteten WMAI
        xml_bytes: das XRechnung-XML als UTF-8-Bytes
        filename: Anhang-Dateiname (z.B. '144853.xml')
        conn: oracledb-Connection mit Write-Rechten

    Returns:
        {'wtxt_id', 'wmaa_id', 'wmai_id'}

    Raises:
        RuntimeError: WMAI war beim UPDATE nicht mehr BLOCKSEND=1 (Race
                      oder fremder Eingriff). Aufgerufene Transaktion
                      ist bereits zurueckgerollt.
    """
    # WMAA_FILENAME ist VARCHAR2(128) NOT NULL - bei Ueberlaenge zurechtschneiden
    safe_name = filename[:WMAA_FILENAME_MAX]
    cur = conn.cursor()
    try:
        # 1) Neue WTXT_ID
        cur.execute("SELECT SEQ_WTXT.NEXTVAL FROM DUAL")
        wtxt_id = cur.fetchone()[0]

        # 2) WTXT-Insert (DOCFORMAT=6 Email-Attachment, COMPRESSED=0 Roh)
        # NB: ':data' und ':size' sind Oracle-Reserved-Words als Bind-Namen
        # (ORA-01745) - daher 'blob_data' / 'blob_size'.
        cur.execute(
            """
            INSERT INTO WTXT (WTXT_ID, WTXT_DATA, WTXT_DOCFORMAT, WTXT_SIZE, WTXT_COMPRESSED)
            VALUES (:wtxt_id, :blob_data, 6, :blob_size, 0)
            """,
            {"wtxt_id": wtxt_id, "blob_data": xml_bytes, "blob_size": len(xml_bytes)},
        )

        # 3) Neue WMAA_ID
        cur.execute("SELECT SEQ_WMAA.NEXTVAL FROM DUAL")
        wmaa_id = cur.fetchone()[0]

        # 4) WMAA-Insert (Junction)
        cur.execute(
            """
            INSERT INTO WMAA
                (WMAA_ID, WMAA_WMAI_ID, WMAA_ATTACHMENT_WTXT_ID, WMAA_FILENAME)
            VALUES (:wmaa_id, :wmai_id, :wtxt_id, :filename)
            """,
            {
                "wmaa_id": wmaa_id, "wmai_id": wmai_id,
                "wtxt_id": wtxt_id, "filename": safe_name,
            },
        )

        # 5) WMAI entblocken (nur wenn vorher BLOCKSEND=1 und SENT=0)
        cur.execute(
            """
            UPDATE WMAI SET WMAI_BLOCKSEND=0
             WHERE WMAI_ID=:wmai_id
               AND WMAI_BLOCKSEND=1
               AND WMAI_SENT=0
            """,
            {"wmai_id": wmai_id},
        )
        if cur.rowcount != 1:
            raise RuntimeError(
                f"WMAI nicht im erwarteten Zustand (id={wmai_id}, "
                f"erwartet BLOCKSEND=1 + SENT=0, betroffene Zeilen={cur.rowcount})"
            )

        # 6) WMAI_ERROR clearen (Reset falls vorheriger Versuch failed war)
        cur.execute(
            "UPDATE WMAI SET WMAI_ERROR = NULL WHERE WMAI_ID = :wmai_id",
            {"wmai_id": wmai_id},
        )

        conn.commit()
        logger.info(
            "Suite8-Attach erfolgreich: wmai=%s wmaa=%s wtxt=%s size=%d",
            wmai_id, wmaa_id, wtxt_id, len(xml_bytes),
        )
        return {"wtxt_id": wtxt_id, "wmaa_id": wmaa_id, "wmai_id": wmai_id}
    except Exception:
        conn.rollback()
        raise


def find_pending_wmai(conn, limit: int = 50) -> list[dict]:
    """Sucht WMAI-Mails die auf einen XRechnung-Anhang warten.

    Kriterium: WMAI_BLOCKSEND=1 AND WMAI_SENT=0. Liefert die
    Felder die der Pattern-Parser braucht.

    Returns:
        Liste von Dicts: {wmai_id, filename, subject, to}
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT WMAI_ID, WMAI_ATTACHMENT_FILE_NAME, WMAI_SUBJECT, WMAI_TO
          FROM WMAI
         WHERE WMAI_BLOCKSEND=1
           AND WMAI_SENT=0
         ORDER BY WMAI_ID
         FETCH FIRST :lim ROWS ONLY
        """,
        {"lim": int(limit)},
    )
    rows = cur.fetchall()
    return [
        {"wmai_id": r[0], "filename": r[1] or "", "subject": r[2] or "", "to": r[3] or ""}
        for r in rows
    ]


def verify_attach_path() -> dict:
    """Smoke-Test: legt eine Dummy-WMAI an, haengt Dummy-XML an, raeumt wieder weg.

    Wirft Exception wenn Schreib-Pfad blockiert ist (z.B. fehlende
    INSERT-Rechte fuer V8LIVE). Suite8-Mailer-Service wird NICHT
    aktiviert weil die Dummy-WMAI BLOCKSEND=0 nach Cleanup nicht mehr
    existiert.

    Returns: Dict ohne 'ok'-Key (der wird vom Caller hinzugefuegt) -
    Caller in api/setup.py macht {'ok': True, **result}.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        # Dummy Body-WTXT
        cur.execute("SELECT SEQ_WTXT.NEXTVAL FROM DUAL")
        body_wtxt = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO WTXT (WTXT_ID, WTXT_DATA, WTXT_DOCFORMAT, WTXT_SIZE, WTXT_COMPRESSED)"
            " VALUES (:id, :d, 1, :s, 0)",
            {"id": body_wtxt, "d": b"<p>verify</p>", "s": 13},
        )
        # Dummy WMAI
        cur.execute("SELECT SEQ_WMAI.NEXTVAL FROM DUAL")
        wmai_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO WMAI
               (WMAI_ID, WMAI_BODY_WTXT_ID, WMAI_FIDELIODATE, WMAI_SENT,
                WMAI_NO_OF_ATTEMPTS, WMAI_SENDER, WMAI_TO, WMAI_SUBJECT,
                WMAI_BLOCKSEND)
               VALUES (:id, :body, SYSDATE, 0, 99, 'verify-system',
                       'verify@invalid.example', 'XRechnung-Setup-Verify (cleanup)', 1)""",
            {"id": wmai_id, "body": body_wtxt},
        )
        conn.commit()

        # Anhaengen
        attach_result = attach_xml_to_wmai(
            wmai_id=wmai_id, xml_bytes=b"<verify/>",
            filename="verify.xml", conn=conn,
        )

        # Cleanup - Reihenfolge WTXT-Anhang VOR WMAA (sonst Subquery leer)
        cur.execute("DELETE FROM WTXT WHERE WTXT_ID=:id", {"id": attach_result["wtxt_id"]})
        cur.execute("DELETE FROM WMAA WHERE WMAA_WMAI_ID=:id", {"id": wmai_id})
        cur.execute("DELETE FROM WMAI WHERE WMAI_ID=:id", {"id": wmai_id})
        cur.execute("DELETE FROM WTXT WHERE WTXT_ID=:id", {"id": body_wtxt})
        conn.commit()

        return {
            "wmai_id": wmai_id,
            "wmaa_id": attach_result["wmaa_id"],
            "wtxt_id": attach_result["wtxt_id"],
            "message": "Schreib-Pfad funktioniert (Insert + Delete erfolgreich)",
        }


WMAI_ERROR_MAX = 2000


def set_wmai_error(wmai_id: int, error_text, conn) -> None:
    """Setzt WMAI_ERROR fuer die gegebene WMAI. None -> NULL (Reset).
    Truncated auf 2000 Zeichen (Suite8-Schema-Limit).
    """
    if error_text is not None:
        error_text = str(error_text)[:WMAI_ERROR_MAX]
    cur = conn.cursor()
    cur.execute(
        "UPDATE WMAI SET WMAI_ERROR = :err WHERE WMAI_ID = :wmai_id",
        {"err": error_text, "wmai_id": wmai_id},
    )
    conn.commit()


def get_wmai_error(wmai_id: int, conn):
    """Liest WMAI_ERROR. Liefert None wenn unbesetzt oder Zeile nicht gefunden."""
    cur = conn.cursor()
    cur.execute(
        "SELECT WMAI_ERROR FROM WMAI WHERE WMAI_ID = :wmai_id",
        {"wmai_id": wmai_id},
    )
    row = cur.fetchone()
    if row is None:
        return None
    return row[0]
