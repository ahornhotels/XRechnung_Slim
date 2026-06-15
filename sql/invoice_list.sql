-- invoice_list.sql
-- Liste der letzten n Tage Rechnungen fuer UI
-- Bindvariable: :days (Anzahl Tage zurueck, z.B. 30)
-- Liefert max. 500 Rechnungen, neueste zuerst

SELECT
  zinv_id,
  zinv_number,
  TO_CHAR(zinv_date, 'YYYY-MM-DD') AS zinv_date,
  zinv_role,
  (SELECT xcms_name1 FROM xcms WHERE xcms_id = zinv_xcms_id) AS customer_name
FROM zinv
WHERE zinv_date >= TRUNC(SYSDATE) - :days
  AND zinv_role IN (0, 3, 31)
ORDER BY zinv_date DESC, zinv_id DESC
FETCH FIRST 500 ROWS ONLY
