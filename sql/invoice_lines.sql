-- invoice_lines.sql
-- Extrahiert aus View TBH_LR_DE_PEPPOL_XML_FOL_DET (VIEWS_Customized_final.txt, Zeilen 190-258)
-- TBH_NUM_TO_CHAR ersetzt durch TO_CHAR(x, '99999990D99', 'NLS_NUMERIC_CHARACTERS=''.,''')
-- Bindvariable: :zinv_id

select
ZINV_ID ZINV_ID,
InvoicedQuantity InvoicedQuantity,
LineExtensionAmount LineExtensionAmount,
TO_CHAR(LineExtensionAmount_Number-round(LineExtensionAmount_Number*ClassifiedTaxCategoryPercent/(100+ClassifiedTaxCategoryPercent),2), '99999990D99', 'NLS_NUMERIC_CHARACTERS=''.,''') LineExtensionAmountNet,
LineExtensionAmount_Number-round(LineExtensionAmount_Number*ClassifiedTaxCategoryPercent/(100+ClassifiedTaxCategoryPercent),2) LineExtensionAmountNet_number,
round(LineExtensionAmount_Number*ClassifiedTaxCategoryPercent/(100+ClassifiedTaxCategoryPercent),2) LineExtensionAmountVat,
round(LineExtensionAmount_Number*ClassifiedTaxCategoryPercent/(100+ClassifiedTaxCategoryPercent),2) LineExtensionAmountVat_Number,
ItemCode ItemCode,
ItemName ItemName,
ClassifiedTaxCategoryID ClassifiedTaxCategoryID,
ClassifiedTaxCategoryPercent ClassifiedTaxCategoryPercent,
TaxSchemeID TaxSchemeID,
DepositZinvId DepositZinvId,
DepositInvoiceNumber DepositInvoiceNumber,
DepositInvoiceDate DepositInvoiceDate,
OriginYresId OriginYresId,
nvl(OriginXcmsRaw, (select y.yres_xcms_id from yres y where y.yres_id=OriginYresId)) OriginXcmsId,
(select n.name2 from v8_rep_name n where n.xcms_id=nvl(OriginXcmsRaw, (select y.yres_xcms_id from yres y where y.yres_id=OriginYresId))) OriginGuestName,
-- Zimmer am Buchungstag (sonst letzter Tag davor, z. B. Abreisetag; vor der
-- Anreise das erste Zimmer). Aggregiert: mehrere YDET-Zeilen je Tag sind
-- kein ORA-01427.
nvl((select max(r.yrms_shortdesc) keep (dense_rank last order by t.ydet_date) from ydet t, yrms r
      where r.yrms_id=t.ydet_yrms_id and t.ydet_yres_id=OriginYresId and t.ydet_date<=OriginPostDate),
    (select max(r.yrms_shortdesc) keep (dense_rank first order by t.ydet_date) from ydet t, yrms r
      where r.yrms_id=t.ydet_yrms_id and t.ydet_yres_id=OriginYresId)) OriginRoom,
(select to_char(trunc(y.yres_exparrtime),'YYYY-MM-DD') from yres y where y.yres_id=OriginYresId) OriginArrival,
(select to_char(trunc(y.yres_expdeptime),'YYYY-MM-DD') from yres y where y.yres_id=OriginYresId) OriginDeparture,
TO_CHAR(LineExtensionAmount_Number-round(LineExtensionAmount_Number*ClassifiedTaxCategoryPercent/(100+ClassifiedTaxCategoryPercent),2), '99999990D99', 'NLS_NUMERIC_CHARACTERS=''.,''') PriceAmount
from
(
select
zpil_zinv_id zinv_id,
1  InvoicedQuantity,
TO_CHAR(round(z.zpos_grossunitprice*z.zpos_quantity,2), '99999990D99', 'NLS_NUMERIC_CHARACTERS=''.,''') LineExtensionAmount,
(round(z.zpos_grossunitprice*z.zpos_quantity,2)) LineExtensionAmount_Number,
to_char(round(z.zpos_unitprice,2),'999999990D99','NLS_NUMERIC_CHARACTERS=''.,''') LineExtensionAmountNet,
round(z.zpos_unitprice*z.zpos_quantity,2) LineExtensionAmountNet_number,
TO_CHAR(round(NVL((SELECT SUM(DECODE(ZPOS.ZPOS_CDT,5,(DECODE(ZPOS.ZPOS_PAIDOUT,1,(ZPOS.ZPOS_UNITPRICE*ZPOS.ZPOS_QUANTITY),(ZPOS.ZPOS_UNITPRICE*ZPOS.ZPOS_QUANTITY))),ZPOS.ZPOS_UNITPRICE*ZPOS.ZPOS_QUANTITY)) FROM ZPOS WHERE ZPOS.ZPOS_CDT=2 AND ZPOS.ZPOS_TAXLINK_ID=z.ZPOS_TAXLINK_ID GROUP BY ZPOS.ZPOS_TAXLINK_ID),0),2), '99999990D99', 'NLS_NUMERIC_CHARACTERS=''.,''') LineExtensionAmountVat,
(select zdco.zdco_numericdesc from zdco where zdco.zdco_id=z.zpos_zdco_id)  ItemCode,
z.zpos_descript  ItemName,
decode(NVL((SELECT SUM(DECODE(ZPOS.ZPOS_CDT,5,(DECODE(ZPOS.ZPOS_PAIDOUT,1,(ZPOS.ZPOS_UNITPRICE*ZPOS.ZPOS_QUANTITY),(ZPOS.ZPOS_UNITPRICE*ZPOS.ZPOS_QUANTITY))),ZPOS.ZPOS_UNITPRICE*ZPOS.ZPOS_QUANTITY)) FROM ZPOS WHERE ZPOS.ZPOS_CDT=2 AND ZPOS.ZPOS_TAXLINK_ID=z.ZPOS_TAXLINK_ID GROUP BY ZPOS.ZPOS_TAXLINK_ID),0),0,'Z','S') ClassifiedTaxCategoryID,
(select evaluatemath(replace((replace(ztcd_udf,'x',100)),';',',')) from zpos Z2,ztcd where Z2.zpos_taxlink_id=z.zpos_taxlink_id and Z2.zpos_cdt=2 and Z2.zpos_ztcd_id=ztcd.ztcd_id)  ClassifiedTaxCategoryPercent,
'VAT' TaxSchemeID,
-- Anzahlungsabbuchung beim Check-in: negatives DEx/MSx-Paar mit Verweis auf die
-- Anzahlungsrechnung (ZINV_ROLE=1). xml_builder macht daraus je Steuersatz einen
-- Abschlag "Abzueglich Anzahlungsrechnung Nr. ... vom ..." plus BG-3.
z.zpos_deposit_zinv_id DepositZinvId,
(select d.zinv_number from zinv d where d.zinv_id=z.zpos_deposit_zinv_id) DepositInvoiceNumber,
(select to_char(d.zinv_date,'YYYY-MM-DD') from zinv d where d.zinv_id=z.zpos_deposit_zinv_id) DepositInvoiceDate,
-- Herkunft je Buchung (Gast/Zimmer fuer Gastzeile und Gruppenrechnung).
-- Reservierung = ZPOS_ORIGINATED_YRES_ID (Fallback ZPOS_YRES_ID), Gast =
-- ZPOS_ORIGINATED_XCMS_ID. Auf einem Finanzkonto entstandene Buchungen
-- (ZPOS_ORIGINATED_ZFAC_ID) haben weder Gast noch Zimmer. Aufgeloest wird
-- im aeusseren SELECT, damit die Ausdruecke nicht je Spalte wiederholt werden.
z.zpos_id ZposId,
case when z.zpos_originated_zfac_id is not null then to_number(null)
     else nvl(z.zpos_originated_yres_id, z.zpos_yres_id) end OriginYresId,
case when z.zpos_originated_zfac_id is not null then to_number(null)
     else z.zpos_originated_xcms_id end OriginXcmsRaw,
trunc(z.zpos_postdate) OriginPostDate,
to_char(round(z.zpos_unitprice,2),'999999990D99','NLS_NUMERIC_CHARACTERS=''.,''') PriceAmount
from
zpil,zpos z
where
z.zpos_id=zpil_zpos_id
and z.zpos_cdt=1
and zpil_zinv_id = :zinv_id
and nvl(round(z.zpos_grossunitprice*z.zpos_quantity,2),0)<>0
)
order by ZposId
