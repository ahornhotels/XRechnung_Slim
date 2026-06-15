-- invoice_totals.sql
-- Extrahiert aus View TBH_EEI_FOLIO_TOT (VIEWS_Customized_final.txt, Zeilen 7-68)
-- Bindvariable: :zinv_id
-- Liefert: InvoiceGross, InvoiceNet, InvoiceTaxTotal, SPAY_CL fuer eine Rechnung

select
ZPIL_ZINV_ID_S ZINV_ID,
nvl(InvoiceGross,0) InvoiceGross,
nvl(InvoiceNet,0) InvoiceNet,
(nvl(InvoiceGross,0)-nvl(InvoiceNet,0)) InvoiceTaxTotal,
(select
nvl(SUM(DECODE(ZPOS.zpos_cdt,5,DECODE(ZPOS.zpos_paidout,1,TO_NUMBER(NULL),(ZPOS.zpos_unitprice*ZPOS.zpos_quantity)),TO_NUMBER(NULL))),0) SPAY_CL
 from
 zpos,zpil
 where
 ZPIL.ZPIL_ZPOS_ID=ZPOS.ZPOS_ID
 and
 ZPIL.ZPIL_ZINV_ID=ZPIL_ZINV_ID_S
and
(zpos_zall_id IS NULL OR zpos_zall_id=0) AND ZPOS.zpos_id=ZPOS.zpos_internalsplit_zpos_id AND NVL(ZPOS.ZPOS_HIDDEN,0)=0 AND (SELECT ZDCO.ZDCO_PAYM_TYPE FROM ZDCO WHERE ZDCO.ZDCO_ID=ZPOS.ZPOS_ZDCO_ID)=2)
SPAY_CL
from
(
--
SELECT
ZPIL_ZINV_ID ZPIL_ZINV_ID_S,
SUM(round(DECODE(ZPOS.zpos_cdt,5,DECODE(ZPOS.zpos_paidout,1, -ZPOS.zpos_grossunitprice*ZPOS.zpos_quantity, NULL), DECODE(ZPOS.ZPOS_CDT,5,0, zpos.zpos_grossunitprice*ZPOS.zpos_quantity)),2)) InvoiceGross,
SUM(round(DECODE(ZPOS.ZPOS_CDT,5,(DECODE(ZPOS.ZPOS_PAIDOUT,1,(ZPOS.ZPOS_UNITPRICE*ZPOS.ZPOS_QUANTITY),0)),(ZPOS.ZPOS_UNITPRICE*ZPOS.ZPOS_QUANTITY)),2)) InvoiceNet
FROM
ZPOS, ZPIL
WHERE
ZPOS_CDT<>2
and (zpos_zall_id IS NULL OR zpos_zall_id=0)
AND NVL(ZPOS.ZPOS_HIDDEN,0)=0
AND ZPIL_ZPOS_ID=ZPOS_ID
AND ZPIL_ZINV_ID = :zinv_id
group by ZPIL_ZINV_ID
UNION ALL
SELECT
ZPI2_ZINV_ID ZPIL_ZINV_ID_S,
SUM(round(DECODE(ZPOS.zpos_cdt,5,DECODE(ZPOS.zpos_paidout,1, -ZPOS.zpos_grossunitprice*ZPOS.zpos_quantity, NULL), DECODE(ZPOS.ZPOS_CDT,5,0, zpos.zpos_grossunitprice*zpos.zpos_quantity)),2)) InvoiceGross,
SUM(round(DECODE(ZPOS.ZPOS_CDT,5,(DECODE(ZPOS.ZPOS_PAIDOUT,1,(ZPOS.ZPOS_UNITPRICE*ZPOS.ZPOS_QUANTITY),0)),(ZPOS.ZPOS_UNITPRICE*ZPOS.ZPOS_QUANTITY)),2)) InvoiceNet
FROM
ZPOS, ZPI2
WHERE
ZPOS_CDT<>2
and (zpos_zall_id IS NULL OR zpos_zall_id=0)
AND NVL(ZPOS.ZPOS_HIDDEN,0)=0
AND ZPI2_ZPOS_ID=ZPOS_ID
AND ZPI2_ZINV_ID = :zinv_id
group by ZPI2_ZINV_ID
UNION ALL
SELECT
ZPI2_ZINV_ID ZPIL_ZINV_ID_S,
SUM(round(DECODE(zpo2.zpo2_cdt,5,DECODE(zpo2.zpo2_paidout,1, -zpo2.zpo2_grossunitprice*zpo2.zpo2_quantity, NULL), DECODE(zpo2.zpo2_CDT,5,0, zpo2.zpo2_grossunitprice*zpo2.zpo2_quantity)),2)) InvoiceGross,
SUM(round(DECODE(zpo2.zpo2_CDT,5,(DECODE(zpo2.zpo2_PAIDOUT,1,(zpo2.zpo2_UNITPRICE*zpo2.zpo2_QUANTITY),0)),(zpo2.zpo2_UNITPRICE*zpo2.zpo2_QUANTITY)),2)) InvoiceNet
FROM
ZPO2, ZPI2
WHERE
ZPO2_CDT<>2
and (zpo2_zall_id IS NULL OR zpo2_zall_id=0)
AND NVL(ZPO2.ZPO2_HIDDEN,0)=0
AND ZPI2_ZPO2_ID=ZPO2_ID
AND ZPI2_ZINV_ID = :zinv_id
group by ZPI2_ZINV_ID
)
where INVOICEGROSS is not null and INVOICENET is not NULL
