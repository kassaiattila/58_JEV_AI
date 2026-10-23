Egy magyar **ivóvíz (víziközmű) számlát** kapsz — a **Fővárosi Vízművek** ivóvíz-szolgáltatási számláját.
Ez egy Díjbeszedő Holding „Terhelési összesítő" kötegből **SZEGMENTÁLT, ÖNÁLLÓ víz-számla**: a Díjbeszedő
mint beszedő a fejlécben szerepelhet, de a **tényleges szolgáltató a Fővárosi Vízművek** — a `supplier_name`
a Vízművek (nem a Díjbeszedő). **EGY konkrét számla** (egy számlaszám, egy végösszeg), NEM a köteg fedőlapja
(Terhelési összesítő), és NEM a csatorna/szennyvíz-számla (az külön Fővárosi Csatornázási Művek számla).

Olvasd ki a séma szerint, minden mezőt pontosan ahogy nyomtatva. `null` ahol a mező nem szerepel.

- **`invoice_number`**: EZEN a víz-számlán szereplő számlaszám (Vízművek, jellemzően `FVV/…` alak; nem a köteg
  Terhelési-összesítő száma).
- **`amount_due` / `gross_total` / `net_total` / `vat_total`**: EZEN a víz-számlán szereplő összegek (a
  bruttó = nettó + ÁFA = fizetendő reconcile-ol).
- **`meter_reading_start` / `meter_reading_end` / `consumption_m3`**: a (fő)vízmérő induló és záró állása m3-ben,
  és az elszámolt ivóvíz-mennyiség m3-ben. Plain decimal STRING, a nyomtatott alakban.
- **`line_items`**: a tételes díjsorok — ivóvíz-fogyasztás, locsolási mellékmérő, alapdíj, ügyviteli díj —,
  mindegyik a saját nettó/ÁFA/bruttó értékével. (A szennyvíz/csatorna tételek a KÜLÖN csatorna-számlán vannak.)
- **Pénzmezők**: plain decimal STRING, pont a tizedes-elválasztó (`12345.67`), ezres-elválasztó NÉLKÜL.
- **Dátumok**: ISO 8601 (`YYYY-MM-DD`).

Csak a séma mezőit add vissza, szigorú JSON-ban.
