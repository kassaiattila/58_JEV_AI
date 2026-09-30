Egy magyar **kommunális hulladék (hulladékgazdálkodási közszolgáltatás) számlát** kapsz — a MOHU MOL
Hulladékgazdálkodási Zrt. / NHKV számláját. Ez egy Díjbeszedő Holding „Terhelési összesítő" kötegből
**SZEGMENTÁLT hulladék-blokk**: a Díjbeszedő mint beszedő a fejlécben szerepelhet, de a **tényleges
szolgáltató a MOHU/NHKV** — a `supplier_name` a MOHU/NHKV (nem a Díjbeszedő). Ez NEM a köteg fedőlapja
(Terhelési összesítő), hanem EGY konkrét szolgáltató számlája.

Olvasd ki a séma szerint, minden mezőt pontosan ahogy nyomtatva. `null` ahol a mező nem szerepel.

- **`invoice_number`**: EZEN a hulladék-számlán szereplő számlaszám (nem a köteg Terhelési-összesítő száma).
- **`amount_due` / `gross_total` / `net_total` / `vat_total`**: EZEN a hulladék-számlán szereplő összegek.
- **`service_description`**: a hulladékgazdálkodási szolgáltatás megnevezése (pl. Kommunális hulladék gyűjtése
  és kezelése).
- **`line_items`**: a tételes díjsorok — kommunális hulladék gyűjtése/kezelése, edényzet-alapdíj, ügyviteli díj.
  A hulladék-számla **NEM mérés-alapú** (nincs vízmérő/m3) — az elszámolás edényzet/ürítés/szolgáltatás alapú.
- **Pénzmezők**: plain decimal STRING, pont a tizedes-elválasztó (`12345.67`), ezres-elválasztó NÉLKÜL.
- **Dátumok**: ISO 8601 (`YYYY-MM-DD`).

Csak a séma mezőit add vissza, szigorú JSON-ban.
