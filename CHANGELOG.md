# Változáslista

A kiadások röviden, a legújabb elöl. A részletes kiadási jegyzetek és mérési bizonylatok belső munkaanyagok, a tárban nincsenek. A kiadás szabályai: [fejlesztési útmutató §1](docs/guides/DEVELOPMENT.md).

**A GitHub-történetről:** a tár története 2026-09-30-án egy új kiinduló committal kezdődik; ez a `v1.0.4` utáni kódállapot. A `v1.0.0`–`v1.0.4` címkék a régebbi, csak helyben őrzött történeten vannak. Az új vonalon a `v1.0.5` az első címke.

## Laikus összefoglaló

Ez a lista megmutatja, mit hozott az egyes kiadás. A `v1.0.0` volt az első, a felhasználó által stabilnak jelölt változat: munkacsomagok, receptek, ellenőrzés az irat képén, eredmény és jóváhagyás. A `v1.0.1`–`v1.0.4` javítókörök valódi próbák és átvizsgálások hibáit javították, ezek közül a legfontosabb az adószám-ellenőrzés. A `v1.0.5` biztonsági kör: a GitHubra nem kerülhet személyes adat, a böngésző nem tárolja az irat-adatot, és látszik, melyik kód fut.

## v1.0.5 — 2026-09-30

Biztonsági javítókör, ingyenes, fizetős hívás nélkül.

- **A belső munkaanyag nincs a gitben.** Az átadókat, terveket, jelentéseket, a teendőlistát és a döntésnaplót a git nem követi; a napi mentés helyben és a második mentési helyen is viszi őket. A kódtári dokumentum nem linkel rájuk, ezt teszt ellenőrzi.
- **Adatőr commit és feltöltés előtt.** Megállít, ha a gitbe kerülő sorokban valódi alakú adószám, bankszámlaszám, e-mail-cím, telefonszám vagy kulcs van. Megállít akkor is, ha belső munkaanyag, irat, kép, adattár vagy bináris fájl kerülne a gitbe, és ha a régi történet menne fel. Bekapcsolás klónonként: `python -m jav.cli hooks-install`.
- **Böngészős védőfejlécek minden válaszon.**
  - A felület csak a saját fájljait tölti be, és nem ágyazható be más oldalba.
  - Az irat-adatot (az oldalképet is) a böngésző nem tárolja a lemezén.
  - A kattintható végpontlista kikapcsolva, mert külső tárhelyről töltene programkódot. A gépi végpontlista marad (`/api/openapi.json`).
- **Egységes verzió.** A verzió egyetlen forrása a projektleíró. A Rendszer oldal és az egészség-végpont a futó verziót és azt a commitot mutatja, amellyel a szolgáltatás elindult.
- **Leírások:**
  - új: [biztonsági leírás](docs/SECURITY.md), [felhasználói kézikönyv](docs/guides/USER_GUIDE.md), [a beállítófájlok leírása](docs/guides/CONFIGS.md) és ez a változáslista;
  - a README, az architektúra, a telepítés és a fogalomtár átnézve.

## v1.0.4 — 2026-09-29

A független átvizsgálás négy döntést kérő pontja.

- **Adószám-ellenőrzés:**
  - Az adószámot felismert alakkal ellenőrzi (magyar, közösségi, uniós és néhány gyakori nem uniós), mindkét félre és a külföldi számlára is.
  - A címkét levágja.
  - A telefonszám és a hibás ellenőrzőszámú érték teendőt kap.
- **Jelölt nélküli mező:** „nincs becslés” jelzés és jelenlét-kérdés, 100% helyett.
- **Elveszett betűjel:** a sérült pénznemjelből nem lesz negatív összeg.
- **Típuscsomag nélküli irat:** a felismert, de csomag nélküli típus teendőt kap.

## v1.0.3 — 2026-09-29

Ellenőrzések és a 066-os átvizsgálás döntés nélküli maradéka.

- Bemeneti korlát: fájlméret, oldalszám, oldalkép-képpont.
- A böngésző-eredet pontos egyezéssel: más helyi port nem hívhatja a szolgáltatást.
- Csomag-sebezhetőség- és lefedettség-ellenőrzés, szabályalapú tesztek.
- Iratba rejtett utasítás szondája mesterséges számlákon: a beszúrt utasítás nem terelte el az eredményt.

## v1.0.2 — 2026-09-29

Mély technikai átvizsgálás javításai.

- Jóváhagyási rések zárva.
- A tesztekben maradt valódi adatok kitalált, azonos alakú értékekre cserélve.
- A levélfogadó csak kulccsal fogad, böngészőből érkező kérést elutasít.
- A leállításhoz is kell a felhasználó neve.

## v1.0.1 — 2026-09-29

Közös próba valódi munkán.

- A jelöltkereső bővült: elveszett betűjel, cím alatti számlaszám, nyugta-azonosító, jóváíró számla, OSS- és holland adószám.
- Az új csomag felelőse a létrehozója.
- A költségfoglalás a tényleges út szerint történik.
- A postafiók-számláló az új és az időszak leveleit külön mutatja.
- A levél csatolmány-teendője a futáshoz tartozik.

## v1.0.0 — 2026-09-29

Az első stabil változat.

- **Munkacsomagok és receptek:** iratok felismerése és adatkinyerése, számlák adatainak kinyerése, levelek szándékának felismerése. Próba és éles futás, tartós munkasor, költségkeret, jóváhagyás.
- **Ellenőrzés az irat oldalképén:** bekeretezett mezők, alternatív jelöltek, kijelölés a képen; teendők okonként.
- **Eredmény:**
  - közös táblázat keresés, szűrés és rendezés;
  - letöltés Excelbe, CSV-be, JSON-ba;
  - közmű-költség riport;
  - számlatételek.
- **Postafiók és figyelt mappák:** letöltés a gépen futó Outlookból, ütemezve is; feladatjavaslat a levélből (alapból kikapcsolva, csak ember fogad el).
- **Felület:** magyar és angol nyelv, világos és sötét téma, receptmagyarázat.
- **Üzemi alapok:** állandó napló, napi adattár-mentés helyben és a második mentési helyen, a folyamatállapot-tár ritkítása.
