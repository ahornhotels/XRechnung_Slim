-- invoice_header.sql
-- Extrahiert aus View TBH_LR_DE_PEPPOL_XML_FOL_HEA (VIEWS_Customized_final.txt, Zeilen 72-188)
-- TBH_NUM_TO_CHAR ersetzt durch TO_CHAR(x, '99999990D99', 'NLS_NUMERIC_CHARACTERS=''.,''')
-- Felder aus TBH_EEI_FOLIO_TOT (LineExtensionAmount, TaxExclusiveAmount, TaxInclusiveAmount,
--   PayableAmount, PrepaidAmount) werden als NULL geliefert.
--   Werte kommen aus invoice_totals.sql und werden in Python gejoint.
-- Bindvariable: :zinv_id

select
to_char(2.1) UBLVersionID,
to_char(1.9) CustomizationID_Version,
to_char('DE')  ProfileID,
zinv_number ID,
to_char(zinv_date, 'YYYY-MM-DD') IssueDate,
to_char(ZINV.ZINV_PCDATE, 'HH:MM:SS') IssueTime,
to_char(zinv.zinv_date+to_number((select nvl(wuss_value,'0') from wuss where upper(wuss_name)='UDEF_XRECHNUNG_DUEDAYS_AFTER_INVOICE')),'YYYY-MM-DD')  DueDate,
CASE NVL(zinv_role, 0)
  WHEN 3  THEN '381'  -- Credit Note (UBL/XRechnung-konform)
  WHEN 31 THEN '381'  -- Polish Faktura Korekta auch als 381
  ELSE '380'          -- Invoice fuer alle anderen Rollen
END InvoiceTypeCode,
NVL(zinv_role, 0) ZinvRole,
(SELECT orig.ZINV_NUMBER FROM ZINV orig
  WHERE orig.ZINV_ID = zinv.ZINV_VOID_ZINV_ID) BillingReferenceID,
(SELECT TO_CHAR(orig.ZINV_DATE, 'YYYY-MM-DD') FROM ZINV orig
  WHERE orig.ZINV_ID = zinv.ZINV_VOID_ZINV_ID) BillingReferenceIssueDate,
zwin_freetext1 Note,
zwin_freetext2 Note2,
TO_CHAR(NULL) OrderReference,
to_char(zinv_date, 'YYYY-MM-DD') TaxPointDate,
(select zcur_iso3 from zcur, wuss where wuss_name = 'BaseCurrency' and wuss.wuss_value = zcur_id) DocumentCurrencyCode,
(select zcur_iso3 from zcur, wuss where wuss_name = 'BaseCurrency' and wuss.wuss_value = zcur_id) TaxCurrencyCode,
(select zcur_iso3 from zcur, wuss where wuss_name = 'BaseCurrency' and wuss.wuss_value = zcur_id) PricingCurrencyCode,
(select zcur_iso3 from zcur, wuss where wuss_name = 'BaseCurrency' and wuss.wuss_value = zcur_id) PaymentCurrencyCode,
(select zcur_iso3 from zcur, wuss where wuss_name = 'BaseCurrency' and wuss.wuss_value = zcur_id) PaymentAlternativeCurrencyCode,
to_char((DECODE(NVL(ZWIN.ZWIN_ZFAC_ID,0),0
   ,(SELECT TRUNC(YRES.YRES_EXPARRTIME) FROM YRES WHERE YRES.YRES_ID=ZWIN.ZWIN_YRES_ID)
       ,DECODE((SELECT YRES.YRES_ID FROM YRES WHERE YRES.YRES_NOTCLOSED_ZFAC_ID=ZWIN.ZWIN_ZFAC_ID),NULL
              ,(SELECT TRUNC(ZFAC.ZFAC_EXPVALIDFROM) FROM ZFAC WHERE ZFAC.ZFAC_ID=ZWIN.ZWIN_ZFAC_ID)
              ,(SELECT TRUNC(YRES.YRES_EXPARRTIME) FROM YRES WHERE YRES.YRES_ID=(SELECT YRES.YRES_ID FROM YRES WHERE YRES.YRES_NOTCLOSED_ZFAC_ID=ZWIN.ZWIN_ZFAC_ID))
 ))),'YYYY-MM-DD')  StartDate,
to_char((DECODE(NVL(ZWIN.ZWIN_ZFAC_ID,0),0
   ,(SELECT TRUNC(YRES.YRES_EXPDEPTIME) FROM YRES WHERE YRES.YRES_ID=ZWIN.ZWIN_YRES_ID)
       ,DECODE((SELECT YRES.YRES_ID FROM YRES WHERE YRES.YRES_NOTCLOSED_ZFAC_ID=ZWIN.ZWIN_ZFAC_ID),NULL
              ,(SELECT TRUNC(ZFAC.ZFAC_EXPVALIDUNTIL) FROM ZFAC WHERE ZFAC.ZFAC_ID=ZWIN.ZWIN_ZFAC_ID)
              ,(SELECT TRUNC(YRES.YRES_EXPDEPTIME) FROM YRES WHERE YRES.YRES_ID=(SELECT YRES.YRES_ID FROM YRES WHERE YRES.YRES_NOTCLOSED_ZFAC_ID=ZWIN.ZWIN_ZFAC_ID))
 ))),'YYYY-MM-DD') EndDate,
to_char(null) AccountingCostCode,
nvl((select xmnr_value from xmnr,xmty where xmnr_xmty_id=xmty_id and xmty_SHORTDESC='DXR' and xmnr_xcms_id=zwin_invoice_to_xcms_id),(select name from V8_EDITOR_NAM b where B.GUEST_ID=zinv_xcms_id)) BuyerReference,
to_char(null) OrderReferenceID,
to_char(null) SalesOrderID,
to_char(null) ProjectReferenceID,
(select wuss_value from wuss where wuss_xcms_id=0 and wuss_name='HotelCode') SupplierID,
(select wuss_value from wuss where wuss_xcms_id=0 and wuss_name='Hotelid') SupplierName,
(select wuss_value from wuss where wuss_xcms_id=0 and wuss_name='HotelAddress') SupplierStreetName,
(select wuss_value from wuss where wuss_xcms_id=0 and wuss_name='Hotelcity') SupplierCityName,
(select wuss_value from wuss where wuss_xcms_id=0 and wuss_name='Hotelzipcode') SupplierPostalZone,
(select XCOU.XCOU_ISO2 from xcou where upper(XCOU.XCOU_LONGDESC)=(select upper(wuss_value) from wuss where wuss_xcms_id=0 and wuss_name='Hotelcountry')) SupplierIdentificationCode,
(select wuss_value from wuss where wuss_xcms_id=0 and wuss_name='HotelTaxNumber') SupplierCompanyID,
'VAT' SupplierTaxSchemeID,
case
when exists (select 1 from wuss where upper(wuss_name)='UDEF_XRECHNUNG_FIRMIERUNG')
then
(select wuss_value from wuss where upper(wuss_name)='UDEF_XRECHNUNG_FIRMIERUNG')
else
(select wuss_value from wuss where wuss_name='Hotelid')
end
SupplierRegistrationName,
(select wuss_value from wuss where upper(wuss_name)='UDEF_XRECHNUNG_RESPONSIBLE_NAME')  SupplierContactName,
(select wuss_value from wuss where wuss_xcms_id=0 and wuss_name='Hoteltel') SupplierContactTelephone,
(select wuss_value from wuss where wuss_xcms_id=0 and wuss_name='Hotelemail') SupplierContactElectronicMail,
(select xcms_type from xcms where xcms_id=zinv_xcms_id) xcms_type,
(select  xcms_name1 from xcms where xcms_id=zinv_xcms_id)  xcms_name1,
(select  xcms_name2 from xcms where xcms_id=zinv_xcms_id)  xcms_name2,
(select  xcms_name3 from xcms where xcms_id=zinv_xcms_id)  xcms_name3,
(select name from V8_EDITOR_NAM b where B.GUEST_ID=zinv_xcms_id) CustomerName,
(select xadr_street1 from xadr where xadr_id=zinv_xadr_id)  CustomerStreetName,
(select xadr_city from xadr where xadr_id=zinv_xadr_id)  CustomerCityName,
(select xadr_zip from xadr where xadr_id=zinv_xadr_id)  CustomerPostalZone,
nvl((SELECT XCOM.XCOM_VALUE FROM XCOM, xcmt WHERE XCOM.XCOM_PRIMARY = 1 AND xcom_xcmt_id = xcmt_id and xcmt_type=1 AND xcom_xcms_id = zinv_xcms_id and rownum=1),(select wuss_value from wuss where wuss_xcms_id=0 and wuss_name='Hotelemail'))  CustomerEndpointID,
(select XCOU.XCOU_ISO2 from xadr,xcou where XADR.XADR_XCOU_ID=XCOU.XCOU_ID and  xadr_id=zinv_xadr_id) CustomerIdentificationCode,
decode(zwin_zfac_id,null,(select name6 from v8_rep_name,yres where xcms_id=yres_xcms_id and yres_id=zwin_yres_id),(select name6 from v8_rep_name,zfac where xcms_id=zfac_xcms_id and zfac_id=zwin_zfac_id)) CustomerRegistrationName,
(select zdco_shortdesc from zdco, zpos Z1 where zdco_id=Z1.zpos_zdco_id and Z1.zpos_id=( select max(Z2.zpos_id) from zpos Z2,zpil I2 where Z2.zpos_id=I2.zpil_zpos_id and Z2.zpos_cdt=5 and I2.zpil_zinv_id=zinv_id)) PaymentMeansCode,
(select TRIM(replace(wuss_value, ' ', '')) from wuss where wuss_name='HotelbankIBAN') PayeeFinancialAccountID,
nvl((select wuss_value from wuss where upper(wuss_name)='UDEF_XRECHNUNG_FIRMIERUNG'),(select wuss_value from wuss where wuss_name='Hotelid')) PayeeFinancialAccountName,
(select wuss_value from wuss where wuss_name='HotelbankBIC') PayeeFinancialAccountBIC,
to_char(null) PaymentTerms,
(select zcur_iso3 from zcur, wuss where wuss_name = 'BaseCurrency' and wuss.wuss_value = zcur_id) LineExtensionAmountcurrencyID,
-- Werte aus invoice_totals.sql, in Python gejoint:
TO_CHAR(NULL) LineExtensionAmount,
(select zcur_iso3 from zcur, wuss where wuss_name = 'BaseCurrency' and wuss.wuss_value = zcur_id) TaxExclusiveAmountcurrencyID,
TO_CHAR(NULL) TaxExclusiveAmount,
(select zcur_iso3 from zcur, wuss where wuss_name = 'BaseCurrency' and wuss.wuss_value = zcur_id) TaxInclusiveAmountcurrencyID,
TO_CHAR(NULL) TaxInclusiveAmount,
(select zcur_iso3 from zcur, wuss where wuss_name = 'BaseCurrency' and wuss.wuss_value = zcur_id) PayableAmountcurrencyID,
TO_CHAR(NULL) PayableAmount,
(select zcur_iso3 from zcur, wuss where wuss_name = 'BaseCurrency' and wuss.wuss_value = zcur_id) PrepaidAmountcurrencyID,
TO_CHAR(NULL) PrepaidAmount,
zinv."ZINV_ID",zinv."ZINV_DATE",zinv."ZINV_NUMBER",zinv."ZINV_ZINN_ID",zinv."ZINV_XCMS_ID",zinv."ZINV_ZFST_ID",zinv."ZINV_CITYLEDGER",zinv."ZINV_ZWIN_ID",zinv."ZINV_XADR_ID",zinv."ZINV_CONTACT_XCMS_ID",zinv."ZINV_PRINTED",zinv."ZINV_PCDATE",zinv."ZINV_ROLE",zinv."ZINV_VOID_ZINV_ID",zinv."ZINV_FISCALNUMBER",zinv."ZINV_CORRECTING_ZINV_ID",zinv."ZINV_CITYLEDGERNUMBER",zinv."ZINV_MANUALNUMBER",zinv."ZINV_FISCALINVOICE",zinv."ZINV_NUMBER2",zinv."ZINV_EMAIL",zinv."ZINV_VOID_REASON",zinv."ZINV_EXPORTSTATUS"
from
zinv,zwin
where
zinv_zwin_id=zwin_id
AND zinv.zinv_id = :zinv_id
