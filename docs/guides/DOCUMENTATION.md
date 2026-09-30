# Dokumentációs szabvány

**Érvényes:** 2026-09-27-től (040). **Kinek szól:** a fejlesztést végző modellnek és a felhasználónak. A régi dokumentumok a helyükön maradnak; ez a szabvány az új és a módosított dokumentumokra kötelező.

## Laikus összefoglaló

Eddig ugyanaz az állapot öt helyen is le volt írva (a Claude-utasításokban, a README-ben, a teendőlistán, az átadóban, a belépő oldalon), és ezek időnként eltértek egymástól. Mostantól minden információfajtának egyetlen helye van. A többi hely csak hivatkozik rá. Az aktuális és a történeti anyag külön van, a gépi úton generált oldalakat kézzel nem írjuk.

2026-09-29 óta (070, a felhasználó döntése) a dokumentumok két körbe tartoznak. A **kódtári dokumentum** a kóddal együtt kerül a gitbe és a GitHubra: mit tud a rendszer, hogyan épül fel, hogyan kell telepíteni és fejleszteni. A **belső munkaanyag** (átadók, tervek, jelentések, teendőlista, döntésnapló, útiterv) csak a fejlesztő gépén van. A git nem követi, a napi mentés viszi.

## 1. Alapszabályok

1. **Egy információ, egy hely.** Ha ugyanazt két helyen kellene leírni, az egyik hivatkozás legyen.
2. **Az aktuális és a történeti anyag külön van.** Az aktuális állapot a belépő oldal, a teendőlista és a legfrissebb átadó. A mérési jelentések és a régi átadók dátumozott történeti anyagok, utólag nem írjuk át őket.
3. **Generált oldalt kézzel nem szerkesztünk.** Ilyen az állapotoldal, a folyamatábrák és a hívási helyek katalógusa. A generáló parancsot futtatjuk. Az állapotoldal és a hívási helyek katalógusa a helyi adattárból készül, ezért helyi (070). A folyamatábrák kódtáriak.
4. **Szám csak bizonyítékkal.** Minden mért szám mellett ott van a nyers futás vagy bizonylat helye. A dokumentum nem ígér többet, mint amit a mérés igazol.
5. **Nyelv és forma:** a CLAUDE.md 8. pontja kötelező. Laikus összefoglaló van elöl, a fogalomtár szavait használjuk, kód-azonosító csak a technikai részben szerepelhet.
6. **A kódtári dokumentum és a kód együtt kerül a gitbe**, ugyanabban a commitban, ha ugyanarról a változásról szól. A belső munkaanyag nem kerül commitba (070).
7. **Kódtári dokumentum belső munkaanyagra nem linkel** (070), mert a tárban nincs meg. Ha utalni kell rá, a formája: „szöveg (belső: `reports/…`)”, a `docs/` mappán belüli útvonallal. A belső munkaanyag szabadon hivatkozhat a kódtári dokumentumra. A hivatkozás-teszt (`tests/test_doc_links.py`) ezt ellenőrzi. A belső útvonalak egyetlen listája a `jav/doc_scope.py`; a `.gitignore` ezzel egyezik (`tests/test_doc_scope_070.py`), és a napi mentés is innen olvas. Az útvonalak 2026-09-29 óta nem változtak.

## 2. Dokumentumfajták

| Dokumentum | Kör (070) | Hely | Mire való | Mi NEM kerül bele | Mikor frissül |
|---|---|---|---|---|---|
| Claude-utasítások | kódtári | `CLAUDE.md` | Állandó munkaszabályok, parancsok, szerkezet, csapdák a modellnek | Session-állapot, dátumozott haladás, mérési számok | Ha munkaszabály változik |
| README | kódtári | `README.md` | Mi ez, hogyan indul, mit tud **most**, hová tovább; a kódtári dokumentumok jegyzéke | Mérési történet (az a jelentésekbe kerül) | Ha képesség vagy indítás változik |
| Belépő | belső | `docs/INDEX.md` | Aktuális terv, olvasási útvonalak, a belső anyag (tervek, jelentések, történeti anyagok) jegyzéke | Második teendőlista | Új terv, jelentés vagy útmutató esetén |
| Állapot (generált) | helyi, generált | `docs/STATE.md` | Konfigverziók, kontraktusok, adattár, git-állapot; **nincs gitben** (minden futásnál változik) | Kézi szöveg | `preflight` / Stop-hook |
| Hívási helyek (generált) | helyi, generált | `docs/callsites/` | A JEV-hívási helyek kérdései, küszöbei és a helyi hívásnapló statisztikája | Kézi szöveg | `python -m jav.cli docs` |
| Folyamatleírás (generált) | kódtári | `docs/flows/<flow>/FLOW.md` | A gráf-kontraktusból generált lépések és ábra | Kézi szöveg | `python -m jav.cli flows` |
| Teendőlista | belső | `docs/BACKLOG.md` | Az egyetlen prioritási sor, státusszal és tervazonosítóval | Indoklások hosszan (azok a tervbe kerülnek) | Minden lezárt feladatnál |
| Döntésnapló | belső | `docs/DECISIONS.md` | A felhasználó döntései dátummal, csak bővül | Mérnöki javaslat döntésként | Minden felhasználói döntésnél |
| Fogalomtár | kódtári | `docs/GLOSSARY.md` | Minden szakszó 1–3 mondatban, példával | Szinonimák halmozása | Új fogalom **előtt** |
| Architektúra | kódtári | `docs/ARCHITECTURE.md` | Ami ténylegesen működik; a terv külön jelölve | Tervezett elem késznek feltüntetve | Szerkezeti változásnál |
| Terv | belső | `docs/plans/NNN/PLAN.md` | Egy fejlesztési kör célja, szakaszai, kész-kritériumai | Nyers futásadat | Terv elfogadásakor és szakaszváltáskor (állapot sor) |
| Jelentés | belső | `docs/reports/ÉÉÉÉ-HH-NN-<téma>.md` | Mérés, audit, értékelés következtetése; kiadási jegyzet | Utólag javított eredmény | Egyszer, lezáráskor |
| Útmutató | kódtári | `docs/guides/<TÉMA>.md` | Hogyan csináljunk valamit (telepítés, fejlesztés, új típus) | Állapot és mérési számok | Ha az eljárás változik |
| Átadó | belső | `docs/handoffs/NNN-ÉÉÉÉ-HH-NN-handoff.md` | Session-lezárás: mi készült, döntések, következő lépés, commit | Önálló prioritási lista, kézzel másolt állapotszám | Session végén és szakasz lezárásakor |

**Megszűnő fajta:** a `docs/CONTINUE_PROMPT_NNN.md` fájlok. A folytatás módját az átadó utolsó szakasza adja meg. A meglévő fájlok történeti anyagként megmaradnak.

**Régi gyökérjelentések:** a `docs/*_2026-09-2x.md` fájlok nem költöznek, mert sok helyről hivatkoznak rájuk. A belépő oldal a „Történeti jelentések” alatt sorolja fel őket. Új jelentés már csak a `docs/reports/` alá kerül.

## 3. Kötelező fejléc tervben és jelentésben

```markdown
# <Cím>

**Dátum:** ÉÉÉÉ-HH-NN · **Állapot:** javaslat | elfogadva | folyamatban | kész | elavult (→ utód) · **Kör:** NNN · **Commit:** <rövid hash, ha van>

## Laikus összefoglaló
3–5 mondat: cél · mit csináltunk · mit jelent · mi a döntés.
```

Jelentésben ezután jön a **Bizonyíték** sor (nyers futás, bizonylat, commit), és az **Érvényességi határ**: mit nem állít a jelentés.

## 4. Életciklus

- **Elavulás:** a régi dokumentum első sora alá egy mondat kerül: „Elavult: 2026-…, utódja: [link]”. A dokumentumot nem töröljük és tartalmilag nem írjuk át.
- **Áthelyezés** csak linkellenőrzéssel történhet. A régi helyen marad egy egysoros hivatkozó fájl, ha oda sok link mutat.
- **Terv állapota:** az `Állapot` mezőt a szakaszváltáskor frissítjük. A haladás részletei a teendőlistába kerülnek, nem a tervbe.
- **Átadó:** a korábbiakat soha nem módosítjuk. Az átadó a commit hash-ét is megnevezi, amelyre vonatkozik.

## 5. Session végi ellenőrzőlista

1. Változott képesség? → README „mit tud most” szakasz.
2. Lezárt feladat? → teendőlista státusza.
3. Felhasználói döntés? → döntésnapló, átadó, memória.
4. Új szakszó? → fogalomtár.
5. Mérés? → jelentés a `docs/reports/` alá, benne a nyers futás helye.
6. `python -m jav.cli preflight` zöld → commit (csak kódtári fájlok) → átadó a commit hash-ével (az átadó helyben marad, nem commitoljuk).
