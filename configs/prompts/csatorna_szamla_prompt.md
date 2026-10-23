Egy magyar **szennyvíz (csatorna, víziközmű) számlát** kapsz — a **Fővárosi Csatornázási Művek (FCSM)**
szennyvízelvezetési számláját. Ez egy Díjbeszedő Holding „Terhelési összesítő" kötegből **SZEGMENTÁLT,
ÖNÁLLÓ csatorna-számla**: a Díjbeszedő mint beszedő a fejlécben szerepelhet, de a **tényleges szolgáltató a
Fővárosi Csatornázási Művek** — a `supplier_name` az FCSM (nem a Díjbeszedő, és NEM a Vízművek). **EGY konkrét
számla** (egy számlaszám, egy végösszeg), NEM a köteg fedőlapja (Terhelési összesítő), és NEM a Vízművek
ivóvíz-számlája (az külön, `vizmuvek_szamla`).

Olvasd ki a séma szerint, minden mezőt pontosan ahogy nyomtatva. `null` ahol a mező nem szerepel.

- **`invoice_number`**: EZEN a csatorna-számlán szereplő számlaszám (FCSM; nem a köteg Terhelési-összesítő
  száma, és nem a víz-számla `FVV/…` száma).
- **`amount_due` / `gross_total` / `net_total` / `vat_total`**: EZEN a csatorna-számlán szereplő összegek (a
  bruttó = nettó + ÁFA = fizetendő reconcile-ol).
- **`consumption_m3`**: az elszámolt szennyvíz-mennyiség m3-ben (a szennyvíz a vízfogyasztás alapján számítódik,
  a számla a vízmérő adatait hivatkozhatja). Plain decimal STRING, a nyomtatott alakban. A `meter_reading_*`
  mezőket akkor töltsd, ha a csatorna-számla kiírja a (hivatkozott vízmérő) állását; egyébként `null`.
- **`line_items`**: a tételes díjsorok — szennyvízelvezetés/csatornadíj, alapdíj, ügyviteli díj —, mindegyik a
  saját nettó/ÁFA/bruttó értékével. (Az ivóvíz-fogyasztási tételek a KÜLÖN víz-számlán vannak.)
- **Pénzmezők**: plain decimal STRING, pont a tizedes-elválasztó (`12345.67`), ezres-elválasztó NÉLKÜL.
- **Dátumok**: ISO 8601 (`YYYY-MM-DD`).

Csak a séma mezőit add vissza, szigorú JSON-ban.
