-- invoice_tax.sql
-- Extrahiert aus View TBH_LR_DE_PEPPOL_XML_FOL_TAX (VIEWS_Customized_final.txt, Zeilen 720-757)
-- Der innere Verweis auf TBH_REP_ZPOS_TAX (Zeilen 261-716) wird als CTE inline expandiert.
-- TBH_NUM_TO_CHAR ersetzt durch TO_CHAR(x, '99999990D99', 'NLS_NUMERIC_CHARACTERS=''.,''')
-- Bindvariable: :zinv_id

WITH tbh_rep_zpos_tax AS (
  -- Inlined from TBH_REP_ZPOS_TAX (VIEWS_Customized_final.txt, Zeilen 261-716)
  -- Pre-Filter auf Buchungen der Rechnung fuer Performance:
  SELECT z.ZPOS_ID ZPOS_ID,
          z.ZPOS_POSTDATE ZPOS_POSTDATE,
          z.ZPOS_PCDATE ZPOS_PCDATE,
          ZDCO.ZDCO_ID ZDCO_ID,
          ZDCO.ZDCO_NUMERICDESC ZDCO_NUMERICDESC,
          ZDCO.ZDCO_LONGDESC ZDCO_LONGDESC,
          z.ZPOS_DESCRIPT ZPOS_DESCRIPT,
          z.ZPOS_COMMENT ZPOS_COMMENT,
          z.ZPOS_PHONENR ZPOS_PHONENR,
          z.ZPOS_POSCHECK_NR ZPOS_POSCHECK_NR,
          z.ZPOS_PAIDOUT ZPOS_PAIDOUT,
          z.ZPOS_EXCHANGERATE ZPOS_EXCHANGERATE,
          ZDCO.ZDCO_NONHTLREV ZDCO_NONHTLREV,
          ZDCO.ZDCO_STATS_TYPE ZDCO_STATS_TYPE,
          ZDCO.ZDCO_PAYM_TYPE ZDCO_PAYM_TYPE,
          z.ZPOS_ZCAS_ID ZCAS_ID,
          ZDCO.ZDCO_ZDCG_ID ZDCG_ID,
          z.ZPOS_ZDC2_ID ZDC2_ID,
          (SELECT ZDCG.ZDCG_LONGDESC
             FROM ZDCG
            WHERE ZDCG.ZDCG_ID = ZDCO.ZDCO_ZDCG_ID)
             ZDCG_LONGDESC,
          (SELECT ZCAS.ZCAS_NUMBER
             FROM ZCAS
            WHERE ZCAS.ZCAS_ID = z.ZPOS_ZCAS_ID)
             ZCAS_NUMBER,
          (DECODE (
              z.ZPOS_ZCAS_ID,
              (SELECT WUSS.WUSS_VALUE
                 FROM WUSS
                WHERE     WUSS.WUSS_XCMS_ID = 0
                      AND WUSS.WUSS_NAME = 'NightAuditCashier'), 1,
              0))
             NA_POSTING,
          NVL (
             (  SELECT SUM (
                          DECODE (
                             ZPOS.ZPOS_CDT,
                             5, (DECODE (
                                    ZPOS.ZPOS_PAIDOUT,
                                    1, (  ZPOS.ZPOS_UNITPRICE
                                        * ZPOS.ZPOS_QUANTITY),
                                    (ZPOS.ZPOS_UNITPRICE * ZPOS.ZPOS_QUANTITY))),
                             ZPOS.ZPOS_GROSSUNITPRICE * ZPOS.ZPOS_QUANTITY))
                  FROM ZPOS
                 WHERE ZPOS.ZPOS_TAXLINK_ID = z.ZPOS_TAXLINK_ID
              GROUP BY ZPOS.ZPOS_TAXLINK_ID),
             0)
             GROSS_AMOUNT,
          NVL (
             (  SELECT SUM (
                          DECODE (
                             ZPOS.ZPOS_CDT,
                             5, (DECODE (
                                    ZPOS.ZPOS_PAIDOUT,
                                    1, (  ZPOS.ZPOS_UNITPRICE
                                        * ZPOS.ZPOS_QUANTITY),
                                    (ZPOS.ZPOS_UNITPRICE * ZPOS.ZPOS_QUANTITY))),
                             ZPOS.ZPOS_UNITPRICE * ZPOS.ZPOS_QUANTITY))
                  FROM ZPOS
                 WHERE     ZPOS.ZPOS_CDT <> 2
                       AND ZPOS.ZPOS_TAXLINK_ID = z.ZPOS_TAXLINK_ID
              GROUP BY ZPOS.ZPOS_TAXLINK_ID),
             0)
             NET_AMOUNT,
          round(NVL (
             (  SELECT SUM (
                          DECODE (
                             ZPOS.ZPOS_CDT,
                             5, (DECODE (
                                    ZPOS.ZPOS_PAIDOUT,
                                    1, (  ZPOS.ZPOS_UNITPRICE
                                        * ZPOS.ZPOS_QUANTITY),
                                    (ZPOS.ZPOS_UNITPRICE * ZPOS.ZPOS_QUANTITY))),
                             decode(ZPOS.ZPOS_UNITPRICE,2.395,2.39,ZPOS.ZPOS_UNITPRICE) * ZPOS.ZPOS_QUANTITY))
                  FROM ZPOS
                 WHERE     ZPOS.ZPOS_CDT = 2
                       AND ZPOS.ZPOS_TAXLINK_ID = z.ZPOS_TAXLINK_ID
              GROUP BY ZPOS.ZPOS_TAXLINK_ID),
             0),2)
             TAX_AMOUNT,
          NVL (
             (  SELECT SUM (
                          DECODE (
                             ZPOS.ZPOS_CDT,
                             5, (DECODE (ZPOS.ZPOS_PAIDOUT, 1, 0, 0)),
                             (ZPOS.ZPOS_GROSSUNITPRICE * ZPOS.ZPOS_QUANTITY)))
                  FROM ZPOS
                 WHERE ZPOS.ZPOS_TAXLINK_ID = z.ZPOS_TAXLINK_ID
              GROUP BY ZPOS.ZPOS_TAXLINK_ID),
             0)
             REV_GROSS_AMOUNT,
          NVL (
             (  SELECT SUM (
                          DECODE (ZPOS.ZPOS_CDT,
                                  5, (DECODE (ZPOS.ZPOS_PAIDOUT, 1, 0, 0)),
                                  (ZPOS.ZPOS_UNITPRICE * ZPOS.ZPOS_QUANTITY)))
                  FROM ZPOS
                 WHERE     ZPOS.ZPOS_CDT <> 2
                       AND ZPOS.ZPOS_TAXLINK_ID = z.ZPOS_TAXLINK_ID
              GROUP BY ZPOS.ZPOS_TAXLINK_ID),
             0)
             REV_NET_AMOUNT,
          NVL (
             (  SELECT SUM (
                          DECODE (
                             ZPOS.ZPOS_CDT,
                             5, (DECODE (
                                    ZPOS.ZPOS_PAIDOUT,
                                    1, (  ZPOS.ZPOS_UNITPRICE
                                        * ZPOS.ZPOS_QUANTITY),
                                    (ZPOS.ZPOS_UNITPRICE * ZPOS.ZPOS_QUANTITY))),
                             0))
                  FROM ZPOS
                 WHERE ZPOS.ZPOS_TAXLINK_ID = z.ZPOS_TAXLINK_ID
              GROUP BY ZPOS.ZPOS_TAXLINK_ID),
             0)
             PAY_AMOUNT,
          NVL (
             (  SELECT SUM (
                          DECODE (
                             ZPOS.ZPOS_CDT,
                             5, (DECODE (
                                    ZPOS.ZPOS_PAIDOUT,
                                    1, (  ZPOS.ZPOS_FOREIGNPRICE
                                        * ZPOS.ZPOS_QUANTITY),
                                    (  ZPOS.ZPOS_FOREIGNPRICE
                                     * ZPOS.ZPOS_QUANTITY))),
                             0))
                  FROM ZPOS
                 WHERE     ZPOS.ZPOS_TAXLINK_ID = z.ZPOS_TAXLINK_ID
                       AND ZDCO.ZDCO_PAYM_TYPE = 4
              GROUP BY ZPOS.ZPOS_TAXLINK_ID),
             0)
             FOREIGN_PAY_AMOUNT,
          NVL (
             (  SELECT SUM (
                          DECODE (
                             ZPOS.ZPOS_CDT,
                             5, (DECODE (
                                    ZPOS.ZPOS_PAIDOUT,
                                    1, (  -ZPOS.ZPOS_UNITPRICE
                                        * ZPOS.ZPOS_QUANTITY),
                                    (-ZPOS.ZPOS_UNITPRICE * ZPOS.ZPOS_QUANTITY))),
                             ZPOS.ZPOS_GROSSUNITPRICE * ZPOS.ZPOS_QUANTITY))
                  FROM ZPOS
                 WHERE ZPOS.ZPOS_TAXLINK_ID = z.ZPOS_TAXLINK_ID
              GROUP BY ZPOS.ZPOS_TAXLINK_ID),
             0)
             GROSS_AMOUNT_PAY_MINUS,
          NVL (
             (  SELECT SUM (
                          DECODE (
                             ZPOS.ZPOS_CDT,
                             5, (DECODE (
                                    ZPOS.ZPOS_PAIDOUT,
                                    1, (  -ZPOS.ZPOS_UNITPRICE
                                        * ZPOS.ZPOS_QUANTITY),
                                    (-ZPOS.ZPOS_UNITPRICE * ZPOS.ZPOS_QUANTITY))),
                             ZPOS.ZPOS_UNITPRICE * ZPOS.ZPOS_QUANTITY))
                  FROM ZPOS
                 WHERE     ZPOS.ZPOS_CDT <> 2
                       AND ZPOS.ZPOS_TAXLINK_ID = z.ZPOS_TAXLINK_ID
              GROUP BY ZPOS.ZPOS_TAXLINK_ID),
             0)
             NET_AMOUNT_PAY_MINUS,
          z.ZPOS_CDT ZPOS_CDT,
          NVL (z.zpos_ledgerstatus, 0) ZPOS_LEDGERSTATUS,
          (CASE
              WHEN (SELECT ZLSM.zlsm_fromledger
                      FROM ZLSM
                     WHERE ZLSM.zlsm_zpos_id = z.zpos_id)
                      IS NOT NULL
              THEN
                 (SELECT ZLSM.zlsm_fromledger
                    FROM ZLSM
                   WHERE ZLSM.zlsm_zpos_id = z.zpos_id)
              ELSE
                 NVL (z.zpos_ledgerstatus, 0)
           END)
             org_zpos_ledgerstatus,
          z.ZPOS_ZWIN_ID ZPOS_ZWIN_ID,
          (SELECT ZWIN.ZWIN_WINDOW
             FROM ZWIN
            WHERE ZWIN.ZWIN_ID = z.ZPOS_ZWIN_ID)
             ZWIN_WINDOW,
          z.ZPOS_USER_XCMS_ID ZPOS_USER_XCMS_ID,
          (SELECT XCED.XCED_LOGINNAME
             FROM XCED
            WHERE XCED.XCED_ID = z.ZPOS_USER_XCMS_ID)
             USER_LOGINNAME,
          (SELECT v8_rep_name.NAME2
             FROM v8_rep_name
            WHERE v8_rep_name.XCMS_ID = z.ZPOS_USER_XCMS_ID)
             USER_FULLNAME,
          z.ZPOS_XCMS_ID XCMS_ID,
          (SELECT v8_rep_name.NAME2
             FROM v8_rep_name, zwin
            WHERE     v8_rep_name.XCMS_ID = ZWIN.ZWIN_INVOICE_TO_XCMS_ID
                  AND ZWIN.ZWIN_ID = z.ZPOS_ZWIN_ID)
             GUESTNAME,
          (SELECT ZWIN.ZWIN_INVOICE_TO_XCMS_ID
             FROM zwin
            WHERE ZWIN.ZWIN_ID = Z.ZPOS_ZWIN_ID)
             INVOICE_TO_XCMS_ID,
          (DECODE (NVL (z.ZPOS_ZFAC_ID, 0),
                   0, z.ZPOS_YRES_ID,
                   z.ZPOS_ZFAC_ID))
             YRES_OR_ZFAC_ID,
          z.ZPOS_YRES_ID ZPOS_YRES_ID,
          z.ZPOS_ZFAC_ID ZPOS_ZFAC_ID,
          (DECODE (
              (SELECT NVL (ZWIN.ZWIN_ZFAC_ID, 0)
                 FROM ZWIN
                WHERE ZWIN.ZWIN_ID = z.ZPOS_ZWIN_ID),
              0, (SELECT v8_rep_name.NAME2
                    FROM v8_rep_name, YRES, ZWIN
                   WHERE     v8_rep_name.XCMS_ID = YRES.YRES_XCMS_ID
                         AND YRES.YRES_ID = ZWIN.ZWIN_YRES_ID
                         AND ZWIN.ZWIN_ID = z.ZPOS_ZWIN_ID),
              (SELECT v8_rep_name.NAME2
                 FROM v8_rep_name, ZFAC, ZWIN
                WHERE     v8_rep_name.XCMS_ID = ZFAC.ZFAC_XCMS_ID
                      AND ZFAC.ZFAC_ID = ZWIN.ZWIN_ZFAC_ID
                      AND ZWIN.ZWIN_ID = z.ZPOS_ZWIN_ID)))
             REAL_GUESTNAME,
          (SELECT v8_rep_name.NAME2
             FROM v8_rep_name, YRES, ZWIN
            WHERE     v8_rep_name.XCMS_ID = YRES.YRES_XCMS_ID
                  AND YRES.YRES_ID = ZWIN.ZWIN_YRES_ID
                  AND ZWIN.ZWIN_ID = z.ZPOS_ZWIN_ID)
             YRES_GUESTNAME,
          (SELECT v8_rep_name.NAME2
             FROM v8_rep_name, ZFAC, ZWIN
            WHERE     v8_rep_name.XCMS_ID = ZFAC.ZFAC_XCMS_ID
                  AND ZFAC.ZFAC_ID = ZWIN.ZWIN_ZFAC_ID
                  AND ZWIN.ZWIN_ID = z.ZPOS_ZWIN_ID)
             ZFAC_GUESTNAME,
          (DECODE (
              NVL (z.ZPOS_ZFAC_ID, 0),
              0, (DECODE (
                     (SELECT YRMS.YRMS_SHORTDESC
                        FROM YRMS, YDET
                       WHERE     YRMS.YRMS_ID = YDET.YDET_YRMS_ID
                             AND YDET.YDET_DATE = z.ZPOS_POSTDATE
                             AND YDET.YDET_YRES_ID = z.ZPOS_YRES_ID),
                     NULL, (SELECT YRMS.YRMS_SHORTDESC
                              FROM YRMS, YDET
                             WHERE     YRMS.YRMS_ID = YDET.YDET_YRMS_ID
                                   AND YDET.YDET_DATE + 1 = z.ZPOS_POSTDATE
                                   AND YDET.YDET_YRES_ID = z.ZPOS_YRES_ID),
                     (SELECT YRMS.YRMS_SHORTDESC
                        FROM YRMS, YDET
                       WHERE     YRMS.YRMS_ID = YDET.YDET_YRMS_ID
                             AND YDET.YDET_DATE = z.ZPOS_POSTDATE
                             AND YDET.YDET_YRES_ID = z.ZPOS_YRES_ID))),
              (SELECT DECODE (NVL (ZFAC.ZFAC_ZFAN_ID, 0),
                              0, TO_CHAR (ZFAC.ZFAC_AUTONUMBER),
                              (SELECT ZFAN.ZFAN_LONGDESC
                                 FROM ZFAN
                                WHERE ZFAN.ZFAN_ID = ZFAC.ZFAC_ZFAN_ID))
                 FROM ZFAC
                WHERE ZFAC.ZFAC_ID = z.ZPOS_ZFAC_ID)))
             YRMS_OR_ZFAC_DESC,
          (DECODE (
              (SELECT YRMS.YRMS_SHORTDESC
                 FROM YRMS, YDET
                WHERE     YRMS.YRMS_ID = YDET.YDET_YRMS_ID
                      AND YDET.YDET_DATE = z.ZPOS_POSTDATE
                      AND YDET.YDET_YRES_ID = z.ZPOS_YRES_ID),
              NULL, (SELECT YRMS.YRMS_SHORTDESC
                       FROM YRMS, YDET
                      WHERE     YRMS.YRMS_ID = YDET.YDET_YRMS_ID
                            AND YDET.YDET_DATE + 1 = z.ZPOS_POSTDATE
                            AND YDET.YDET_YRES_ID = z.ZPOS_YRES_ID),
              (SELECT YRMS.YRMS_SHORTDESC
                 FROM YRMS, YDET
                WHERE     YRMS.YRMS_ID = YDET.YDET_YRMS_ID
                      AND YDET.YDET_DATE = z.ZPOS_POSTDATE
                      AND YDET.YDET_YRES_ID = z.ZPOS_YRES_ID)))
             YRMS_SHORTDESC,
          (SELECT ZFAC.ZFAC_LONGDESC
             FROM ZFAC
            WHERE ZFAC.ZFAC_ID = z.ZPOS_ZFAC_ID)
             ZFAC_LONGDESC,
          (  SELECT MAX (ZINV.ZINV_NUMBER)
               FROM ZINV, ZPIL
              WHERE     ZINV.ZINV_ID = ZPIL.ZPIL_ZINV_ID
                    AND ZPIL.ZPIL_ZPOS_ID = z.ZPOS_ID
           GROUP BY z.ZPOS_ID)
             MAX_ZINV_NUMBER,
          (  SELECT MIN (ZINV.ZINV_NUMBER)
               FROM ZINV, ZPIL
              WHERE     ZINV.ZINV_ID = ZPIL.ZPIL_ZINV_ID
                    AND ZPIL.ZPIL_ZPOS_ID = z.ZPOS_ID
           GROUP BY z.ZPOS_ID)
             MIN_ZINV_NUMBER,
          z.ZPOS_INTERNALSPLIT_ZPOS_ID ZPOS_INTERNALSPLIT_ZPOS_ID,
          (DECODE (z.ZPOS_ID, z.ZPOS_INTERNALSPLIT_ZPOS_ID, 1, 0))
             MASTER_SPLIT_POST,
          (DECODE (
              z.ZPOS_ID,
              z.ZPOS_INTERNALSPLIT_ZPOS_ID, NULL,
              (SELECT zdco_s.ZDCO_NUMERICDESC
                 FROM ZDCO zdco_s, ZPOS
                WHERE     zdco_s.ZDCO_ID = ZPOS.ZPOS_ZDCO_ID
                      AND ZPOS.ZPOS_ID = z.ZPOS_INTERNALSPLIT_ZPOS_ID)))
             MASTER_POST_ZDCO_NUMERICDESC,
          (DECODE (
              z.ZPOS_ID,
              z.ZPOS_INTERNALSPLIT_ZPOS_ID, NULL,
              (SELECT zdco_s.ZDCO_LONGDESC
                 FROM ZDCO zdco_s, ZPOS
                WHERE     zdco_s.ZDCO_ID = ZPOS.ZPOS_ZDCO_ID
                      AND ZPOS.ZPOS_ID = z.ZPOS_INTERNALSPLIT_ZPOS_ID)))
             MASTER_POST_ZDCO_LONGDESC,
          (DECODE (SIGN (z.ZPOS_UNITPRICE * z.ZPOS_QUANTITY),
                   -1, DECODE (z.ZPOS_PAIDOUT, 0, 1, 0),
                   1, DECODE (z.ZPOS_PAIDOUT, 1, 1, 0)))
             INVERS_POSTING,
          z.zpos_zcur_id,
          NVL (
             (SELECT ZFAG.ZFAG_TYPE
                FROM ZFAC, ZFAG
               WHERE     ZFAG.ZFAG_ID = ZFAC.ZFAC_ZFAG_ID
                     AND ZFAC.ZFAC_ID = z.ZPOS_ZFAC_ID),
             0)
             ZFAG_TYPE,
          (CASE
              WHEN NVL (
                      (SELECT ZFAG.ZFAG_TYPE
                         FROM ZFAC, ZFAG
                        WHERE     ZFAG.ZFAG_ID = ZFAC.ZFAC_ZFAG_ID
                              AND ZFAC.ZFAC_ID = z.ZPOS_ORIGINATED_ZFAC_ID),
                      0) = 12
              THEN
                 3
              WHEN ZDCO.ZDCO_DEPOSIT = 1
              THEN
                 2
              ELSE
                 1
           END)
             POSTING_TYPE,
          (CASE
              WHEN NVL (
                      (SELECT ZFAG.ZFAG_TYPE
                         FROM ZFAC, ZFAG
                        WHERE     ZFAG.ZFAG_ID = ZFAC.ZFAC_ZFAG_ID
                              AND ZFAC.ZFAC_ID = z.ZPOS_ORIGINATED_ZFAC_ID),
                      0) = 12
              THEN
                 'Voucher'
              WHEN ZDCO.ZDCO_DEPOSIT = 1
              THEN
                 'Deposit'
              ELSE
                 'Hotel'
           END)
             POSTING_TYPE_DESC
     FROM ZPOS z, WDAT, ZDCO
    WHERE     z.ZPOS_CDT IN (2)
          AND z.ZPOS_POSTDATE = WDAT.WDAT_DATE(+)
          AND z.ZPOS_ZDCO_ID = ZDCO.ZDCO_ID
          -- Pre-Filter: nur Buchungen der angefragten Rechnung
          AND z.ZPOS_TAXLINK_ID IN (
            SELECT zpos2.ZPOS_TAXLINK_ID
            FROM zpos zpos2, zpil
            WHERE zpos2.zpos_id = zpil.zpil_zpos_id
              AND zpil.zpil_zinv_id = :zinv_id
          )
)
-- Hauptabfrage: TBH_LR_DE_PEPPOL_XML_FOL_TAX
SELECT
ZINV_ID_S ZINV_ID,
(select zcur_iso3 from zcur where zcur_id=(select wuss_value from wuss where wuss_xcms_id=0 and wuss_name='BaseCurrency')) TaxAmountcurrencyIDTot,
TO_CHAR(round((select sum(taxv2.tax_amount) from tbh_rep_zpos_tax taxv2,zpil zpil2 where zpil2.zpil_zinv_id=ZINV_ID_S and taxv2.zpos_id=zpil2.zpil_zpos_id),2), '99999990D99', 'NLS_NUMERIC_CHARACTERS=''.,''') TaxAmountTot,
(select zcur_iso3 from zcur where zcur_id=(select wuss_value from wuss where wuss_xcms_id=0 and wuss_name='BaseCurrency')) TaxableAmountcurrencyID,
TO_CHAR(round(NET_AMOUNT_S,2), '99999990D99', 'NLS_NUMERIC_CHARACTERS=''.,''') TaxableAmount,
(select zcur_iso3 from zcur where zcur_id=(select wuss_value from wuss where wuss_xcms_id=0 and wuss_name='BaseCurrency')) TaxAmountcurrencyID,
TO_CHAR(round(TAX_AMOUNT_S,2), '99999990D99', 'NLS_NUMERIC_CHARACTERS=''.,''') TaxAmount,
decode(TAX_AMOUNT_S,0,'Z','S') TaxCategoryID,
evaluatemath(replace((replace(ztcd_udf,'x',100)),';',',')) TaxCategoryPercent,
'VAT' TaxScheme,
ztcd."ZTCD_ID",ztcd."ZTCD_ZTXC_ID",ztcd."ZTCD_POSTTO_ZDCO_ID",ztcd."ZTCD_UDF",ztcd."ZTCD_ORDER",ztcd."ZTCD_VALIDFROM",ztcd."ZTCD_VALIDUNTIL",ztcd."ZTCD_INCLUDE",ztcd."ZTCD_NAME",ztcd."ZTCD_PRINTSEPARATE",ztcd."ZTCD_POSTZERO",ztcd."ZTCD_IGNORE_NA_CHECK"
from
(
select
zpil.zpil_zinv_id ZINV_ID_S,
zpos.zpos_ztcd_id ZTCD_ID_S,
sum(round(taxv.net_amount,2)) NET_AMOUNT_S,
sum(round(taxv.tax_amount,2)) TAX_AMOUNT_S
from
tbh_rep_zpos_tax TAXV,zpil,zpos
where
TAXV.zpos_id=zpil_zpos_id
and TAXV.zpos_id=zpos.zpos_id
and zpil_zinv_id = :zinv_id
group by zpil_zinv_id,zpos.zpos_ztcd_id
) TV, ztcd
where
TV.ZTCD_ID_S=ztcd.ztcd_id
