# V8LIVE-Gegenprüfung offener SQL-Fixes

Read-only Prüf-Queries für die SQL-Fixes, die ohne Oracle-Gegenprüfung released
wurden. Alle Queries sind reine `SELECT`s — gefahrlos gegen V8LIVE. In SQL
Developer / sqlplus ausführen. Platzhalter `&…` bzw. `:zinv_id` binden.

---

## 1) v1.10.2 — TaxAmount je Steuercode (BR-CO-14)

**Bug (behoben):** Bei zwei Steuercodes (ZTCD) mit gleichem Prozentsatz bekam jede
TaxSubtotal-Zeile die volle Gruppen-VAT → Summe der Teilbeträge = doppelt →
KoSIT BR-CO-14 lehnte die Rechnung ab. Fix: Korrelation über `ztcd_id` statt
Prozentsatz, `NVL`-Fallback gegen stilles `0.00`.

### 1a) Trigger-Check — gibt es Rechnungen mit 2 gleichprozentigen Steuercodes?
```sql
-- Rechnungen, deren Positionen unter >1 verschiedenen ZTCD-Steuercodes mit
-- IDENTISCHEM Prozentsatz gebucht sind (die kritische Konstellation).
-- 0 Zeilen -> Bug kann nicht auftreten, Fix ist Absicherung.
select zpil_zinv_id, ztcd_pct, count(distinct zpos_ztcd_id) anz_codes
from (
  select p.zpil_zinv_id,
         z.zpos_ztcd_id,
         evaluatemath(replace((replace(t.ztcd_udf,'x',100)),';',',')) ztcd_pct
  from zpil p, zpos z, ztcd t
  where z.zpos_id = p.zpil_zpos_id
    and z.zpos_cdt = 2
    and z.zpos_ztcd_id = t.ztcd_id
)
group by zpil_zinv_id, ztcd_pct
having count(distinct zpos_ztcd_id) > 1
order by anz_codes desc;
```

### 1b) Konsistenz-Check — Summe der TaxSubtotals == TaxAmountTot?
`sql/invoice_tax.sql` mit `:zinv_id` einer Rechnung aus 1a (oder einer normalen)
ausführen. Erwartung: Über alle Ergebniszeilen ist **Summe der Spalte `TaxAmount`
== `TaxAmountTot`** (letzterer ist in jeder Zeile gleich). Vor dem Fix war die
Summe bei zwei gleichprozentigen Codes doppelt so groß.

---

## 2) v1.10.4 — Adress-Fallback deterministisch (Finding 8)

**Bug (behoben):** Fällt die Rechnung mangels `zinv_xadr_id` auf die Primäradresse
zurück, zogen Straße/Ort/PLZ/Land je aus einem eigenen `xadr_primary=1 and
rownum=1` → bei mehreren Primäradressen mischbar. Fix: alle vier aus derselben
`min(xadr_id)`-Zeile.

### 2a) Trigger-Check — Gäste mit mehreren Primäradressen?
```sql
-- 0 Zeilen -> Bug kann nicht auftreten, Fix ist folgenlose Absicherung.
select xadr_xcms_id, count(*) as anz_primaeradressen
from xadr
where xadr_primary = 1
group by xadr_xcms_id
having count(*) > 1
order by anz_primaeradressen desc;
```

### 2b) Determinismus-Check für einen Gast (`&XCMS_ID` aus 2a)
```sql
select
  xa.xadr_id,
  case when xa.xadr_id = (select min(x2.xadr_id) from xadr x2
                          where x2.xadr_xcms_id = xa.xadr_xcms_id
                            and x2.xadr_primary = 1)
       then 'JA' else '' end          as gewaehlt,
  xa.xadr_street1, xa.xadr_city, xa.xadr_zip, xa.xadr_xcou_id
from xadr xa
where xa.xadr_xcms_id = &XCMS_ID
  and xa.xadr_primary = 1
order by xa.xadr_id;
```

### 2c) ALT-vs-NEU-Vergleich für eine Rechnung (`&ZINV_ID`)
```sql
select
  z.zinv_id, z.zinv_number, z.zinv_xadr_id, z.zinv_xcms_id,
  nvl((select xadr_street1 from xadr where xadr_id=z.zinv_xadr_id),
      (select xadr_street1 from xadr where z.zinv_xcms_id=xadr_xcms_id and xadr_primary=1 and rownum=1)) as street_alt,
  nvl((select xadr_street1 from xadr where xadr_id=z.zinv_xadr_id),
      (select xa1.xadr_street1 from xadr xa1 where xa1.xadr_id=(select min(xa2.xadr_id) from xadr xa2 where xa2.xadr_xcms_id=z.zinv_xcms_id and xa2.xadr_primary=1))) as street_neu,
  nvl((select xadr_zip from xadr where xadr_id=z.zinv_xadr_id),
      (select xadr_zip from xadr where z.zinv_xcms_id=xadr_xcms_id and xadr_primary=1 and rownum=1)) as zip_alt,
  nvl((select xadr_zip from xadr where xadr_id=z.zinv_xadr_id),
      (select xa1.xadr_zip from xadr xa1 where xa1.xadr_id=(select min(xa2.xadr_id) from xadr xa2 where xa2.xadr_xcms_id=z.zinv_xcms_id and xa2.xadr_primary=1))) as zip_neu
from zinv z
where z.zinv_id = &ZINV_ID;
```
Erwartung: Rechnung MIT `zinv_xadr_id` oder Gast mit EINER Primäradresse →
`alt == neu`. Nur bei mehreren Primäradressen wird `neu` in sich konsistent.
