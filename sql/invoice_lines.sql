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
to_char(round(z.zpos_unitprice,2),'999999990D99','NLS_NUMERIC_CHARACTERS=''.,''') PriceAmount
from
zpil,zpos z
where
z.zpos_id=zpil_zpos_id
and z.zpos_cdt=1
and zpil_zinv_id = :zinv_id
and nvl(round(z.zpos_grossunitprice*z.zpos_quantity,2),0)<>0
)
