# 58_JAV_AI — AI-flow keretrendszer dokumentumokra és e-mailekre

Burr (folyamatvezérlés) + Pydantic AI (GPT) + JEV/TypeSafe (típusos ítéletek), helyi SQLite-tal, Windows-on.

**Jelenlegi stabil változat: `v1.0.5`** (2026-09-30, biztonsági javítókör: adatőr, böngészős védőfejlécek, egységes verzió, új leírások; [változáslista](CHANGELOG.md)). A kód 2026-09-29 óta a GitHubon is megvan, privát tárban; a GitHub-történet 2026-09-30-án egy új kiinduló committal kezdődik, a régebbi történet csak helyben van ([fejlesztési útmutató §1](docs/guides/DEVELOPMENT.md)).

A kiadási jegyzetek, mérési jelentések, tervek, átadók, a teendőlista és a döntésnapló **belső munkaanyag**: csak a fejlesztő gépén vannak, a tárban nincsenek. Ahol ez a leírás rájuk utal, „(belső: …)” jelölés áll a helyi útvonalukkal (a `docs/` mappán belül).

## Laikus összefoglaló

A rendszer beolvassa a számlákat, egyéb iratokat és leveleket. Felismeri a típusukat, kinyeri az adataikat és ellenőrzi őket; ami bizonytalan, az emberi ellenőrzésre kerül, nem fogadjuk el csendben. Az iratokból munkacsomag készíthető, amelyen egy recept (verziózott feldolgozási leírás) a háttérben, tartós munkasoron fut: költségkerettel, leállás utáni folytatással és okonkénti teendőkkel. Böngészős felületen (`http://127.0.0.1:8930/`), parancssorból és a helyi szolgáltatáson át is használható. A korábbi mérések részletes története a README-történetben olvasható (belső).

## Mit tud most

| Képesség | Állapot | Részletek |
|---|---|---|
| **Iratkategorizálás** (M1): 12 tág típus + ismeretlen, nyelv, kibocsátó | Működik, mérve a régi etalonon | történet: M1 (belső: `reports/2026-09-27-readme-tortenet.md`) |
| **Számla-adatkinyerés** (M2), két úton: kód talál jelöltet + JEV választ (S), vagy GPT kivonat + JEV ellenőrzés (G) | Működik: magyar, külföldi és hat közműszámla-csomag | történet (belső: `reports/2026-09-27-readme-tortenet.md`) |
| **E-mail szándék** (M3): a régi 11 szándék, csatolmányok típusa, következő lépés | Működik; valós pontosság kézi etalon nélkül nem igazolt | bővítés (belső: `EXPANSION_2026-09-22.md`) |
| **OCR** szöveg nélküli PDF-hez: helyi tesseract, gyenge eredménynél fizetős Azure-eszkaláció | Működik; a kihagyott oldalak teendőként jelennek meg | értékelés, F07 (belső: `FRAMEWORK_ASSESSMENT_2026-09-22.md`) |
| **Egységes típusok** (047 T1): mind a 23 régi típus teljes csomag; a felismerés a részletes típust is kiválasztja; irat-feldolgozás recept; a régi eredmények összevetésre behozhatók | Működik; a régi felismerési etalonon a részletes típus 97-ből 95-ször egyezik; a tételes listák (pl. kivonat-tranzakciók) a felületen külön fülön javíthatók, a kivonat-szabályok a javított adaton újrafutnak (048) | T1 jelentés (belső: `reports/2026-09-28-t1-tipusegyesites.md`), [architektúra 10.](docs/ARCHITECTURE.md#10-egységes-dokumentumtípusok-047-t1-2026-09-28) |
| **Tanulási ágak:** forráshoz kötött adatpontjelöltek, csomagtervezetek | Kísérleti | dokumentumtanulás (belső: `DOCUMENT_LEARNING_2026-09-21.md`) |
| **Munkacsomag → futás** (040 K1): csomag mappából, recept, készenlét-ellenőrzés, idempotens indítás rögzített bemenettel, háttér-feldolgozó, próba/éles mód, jóváhagyás | Működik parancssorból; első recept a számla-kivonatolás | [architektúra 6.](docs/ARCHITECTURE.md#6-futtatási-réteg-munkacsomag--futás--feldolgozó-040-k1-2026-09-27) |
| **Megbízható futtatás** (040 K1): hívásnapló és előzetes költségfoglalás, folytatás a mentett lépéstől, okonkénti teendők, részleges OCR jelzése, védett levélfogadó | Működik a feldolgozón át futó úton | [hibaszondák](docs/ARCHITECTURE.md#6-futtatási-réteg-munkacsomag--futás--feldolgozó-040-k1-2026-09-27) |
| **Helyi szolgáltatás** (040 K2): a teljes életút böngésző nélkül is hívható; csak saját gépről, ellenőrzött bemenettel; verziózott mezőjavítás; egypéldányos, szabályosan leállítható feldolgozó | Működik; a felület (K3) erre épül | [architektúra 7.](docs/ARCHITECTURE.md#7-helyi-szolgáltatás-040-k2-2026-09-27) |
| **Munkafelület** (040 K3, 045 K3b): munkacsomagok tételekkel; teendők az irat oldalképén bekeretezett mezőkkel, alternatív jelöltekkel, kijelöléssel a képen; recept és indítás; a futás követése, költsége és jóváhagyása (057 óta a csomag szakaszaiban, lásd lent) | Első változat; élő próba 5 valódi számlán; a gyorsítótáras újrafuttatásban 82 mezőből 77 pontos keret + 1 közelítő (046; előtte 71) | [architektúra 8.](docs/ARCHITECTURE.md#8-munkafelület-040-k3-2026-09-27), élő próba (belső: `reports/2026-09-27-k3-elo-proba.md`) |
| **Postafiók** (048 T2): a gépen futó Outlookból letöltés postafiókkal és időszakkal, ingyenes darabszám-előnézettel, egyszer vagy ütemezve (alap: óránként); az új levelekből munkacsomag a levél-szándék recepttel, a fizetős futást ember indítja | Működik; két valódi postafiókon kipróbálva 2026-09-28 (45 + 2 levél, próba mód), lásd a 051-es átadót | [architektúra 11.](docs/ARCHITECTURE.md#11-postafiók-olvasás-és-ütemezés-048-t2-2026-09-28) |
| **Számlatételek** (053 T3): a magyar és a közmű-számlák tételsorai tételes listaként, tételösszeg- és soronkénti ellenőrzéssel; a közmű-számlák alapból a GPT-úton | Működik; a 49 közmű-iraton a tételösszeg 44-szer kiadja a végösszeget | T3.4 mérés (belső: `reports/2026-09-28-t3-szamlatetelek-meres.md`) |
| **Keretek a képen** (054): minden megtalált mező kerete színezve; a több helyen szereplő érték a legvalószínűbb helyen; a tételsorok helye, sorra kattintva ugrás | Működik; a T3.4 csomagon a mezők 79 %-a, a tételsorok 88 %-a kap helyet | 054-es átadó (belső: `handoffs/054-2026-09-28-handoff.md`) |
| **Riportok** (054 K4): futás-export Excelbe, CSV-be, JSON-ba (iratok, adatpontok oldallal és forrásszöveggel, tételsorok); közmű-költség havonta fogyasztási hely és közmű szerint, hiányzó / részleges / átfedő hónapokkal, cellánként a forrásszámlákkal | Működik; a T3.4 csomagon 6 idősor, 4 ismétlődő számla kiszűrve | [architektúra 10.](docs/ARCHITECTURE.md#10-egységes-dokumentumtípusok-047-t1-2026-09-28) |
| **Egységes adatnézet** (056 U1): minden lista és eredménytábla közös táblázatban (keresés, oszloponkénti szűrés és rendezés, lapozás, oszlopválasztó, kijelölés); a futás-eredmény táblái (057 óta a csomag Eredmény szakaszában); minden legördülő helyett kereshető választó; közös letöltés-panel (Excel / CSV / JSON; minden, szűrt vagy kijelölt sor; oszlopok) | Működik; a T3.4 futás 1336 adatpontja lapozva, szűrve; a futás adata az első kérés után gyorsítótárból jön (10 s helyett 0,1 s) | 056 terv (belső: `plans/056/PLAN.md`), [architektúra 10.](docs/ARCHITECTURE.md#10-egységes-dokumentumtípusok-047-t1-2026-09-28) |
| **Új felület-szerkezet** (057): két fő rész, Munkacsomagok és Beállítások. A csomag szakaszai: Feldolgozás (próba- / éles futás, újrafuttatás), Ellenőrzés (teendők, iratok letöltése), Eredmény (táblák, közmű-költség, letöltés, jóváhagyás); a fejléc gombja a következő lépés. Beállítások: postafiókok, munkamappák (figyelt mappák), felhasználók, megjelenés (világos / sötét), nyelv (magyar / angol), rendszer | Működik; böngészőben ellenőrizve mindkét nyelven és sötét témában | 057 terv (belső: `plans/057/PLAN.md`) |
| **Felület-javítások** (058): csomag elrejtése, átnevezése, üres csomag törlése; az állapotjelvény a teendők lezárása után frissül; kódnevek helyett magyar nevek (recept, levél-szándék, út); rövidített linkek a levélben; egy kiemelt futás-gomb magyarázattal; a korábban használt postafiókok választhatók; az Eredmény csak az adatot tartalmazó nézeteket kínálja; minden táblázat-fejlécen látszik a rendezés; minden mezőnek van magyar neve; a nagy csomag gyorsabban nyílik | Működik; böngészőben ellenőrizve; a 96 iratos csomag megnyitása 3,0 s helyett 0,6 s | 058-as átadó (belső: `handoffs/058-2026-09-28-handoff.md`) |
| **Levelek mint második recept** (058 K5.1–K5.2): a levél-eredmény futásonként megmarad; az Eredmény „Levelek” nézete és a teljes Excel-csomag Levelek lapja (szándék, javasolt következő lépés, csatolmányok, a levél szövegéből látott rész); a szándék kézzel javítható, a következő lépés ebből számolódik; a levél PDF-csatolmányai a csomagban iratként futnak ugyanazzal a recepttel (adatkinyerés is), a levélre visszavezetve | Működik; mesterséges levelekkel tesztelve, a valódi 45 levélen a Levelek nézet ellenőrizve (fizetős hívás nélkül) | 059-es átadó (belső: `handoffs/059-2026-09-28-handoff.md`) |
| **Feladatjavaslat a levélből** (058 K5.3): a régi projekt utasításával a GPT levelenként konkrét teendőt javasol (akció, határidő, felelős), szó szerinti idézettel; kódos kapu ejti ki a nem igazolt javaslatot; archiválandó levélen nem kérünk; elfogadni csak ember tud (levél nézet, Feladatok nézet, Excel Feladatok lap). A levél-receptben alapból kikapcsolva | Mérve: a 47 valódi levélen 4 javaslatot kért levél, 0 teendő, két futásban azonos; kihagyás nélkül 38 hírlevélből 1 kapott hamis teendőt; a régi 7 mesterséges etalon-esetén 14/14 egyezés; 0,21 USD | mérés (belső: `reports/2026-09-28-k5-feladatjavaslat-meres.md`) |
| **Receptmagyarázat és karakteres kezelőelemek** (063): a csomag Recept-kártyáján beállításonként a választott érték jelentése és a tételenkénti költségkeret; Beállítások › Receptek oldal a teljes leírással (mire való, mikor válaszd, mi kell hozzá, lépések, eredmény, az ember teendője); a gombok kiemelőszínű kerettel és ikonnal, a menüpontok nagyobbak | Működik; böngészőben ellenőrizve mindkét nyelven, világos és sötét témában | kiadási jegyzet (belső: `reports/2026-09-29-v1.0.0-kiadas.md`) |
| **Üzemi alapok** (063, 064): a feldolgozó hibás feladaton nem áll le, a félbemaradt munka korlátosan indul újra, a megszakadt letöltés levelei és a figyelt mappa fájljai nem vesznek el; állandó napló (`runs/logs/`); napi adattár-mentés 12:00-kor helyben és a NAS-on (14 marad; 070 óta a belső munkaanyaggal együtt), állapota a Rendszer oldalon; a folyamatállapot-tár lezárt tételenként ritkul | Működik; 16 + 10 üzemi teszt, mentés és NAS-másolat a valódi adattáron ellenőrizve, élő végpróba 0,001 USD | [SETUP 6.](docs/guides/SETUP.md), kiadási jegyzet (belső: `reports/2026-09-29-v1.0.0-kiadas.md`) |
| **Felhasználók és kiosztás** (061, 062): kötelező névválasztás („Ki dolgozik?”), a csomag felelőse, „Csak a saját csomagjaim”, „Mai munkám”; a futás indítása megerősítő oldalon; az elfogadott feladat kézzel „elvégezve” jelölhető | Működik; a név választás, nem azonosítás (nincs bejelentkezés) | [felhasználói kézikönyv](docs/guides/USER_GUIDE.md) |
| **Adat-ellenőrzések** (067, 069 `v1.0.4`): az adószám felismert alakkal és ellenőrzőszámmal, mindkét félre és a külföldi számlára is (a címkét levágja; a telefonszám és a hibás ellenőrzőszámú érték teendőt kap); a jelölt nélküli mező „nincs becslés” jelzést és jelenlét-kérdést kap; az elveszett betűjel nem ad negatív összeget; a típuscsomag nélküli irat teendőt kap; bemeneti korlát (100 MB, 300 oldal, 40 megapixel oldalanként) | Működik; a független audit négy ellenpéldáján visszamérve | [architektúra](docs/ARCHITECTURE.md) |
| **Biztonsági javítókör** (071, `v1.0.5`): adatőr commit és feltöltés előtt (személyes adat, kulcs, belső munkaanyag, irat nem kerülhet a gitbe; a régi történet nem tölthető fel); böngészős védőfejlécek minden válaszon, az irat-adatot a böngésző nem tárolja; a Rendszer oldal és az egészség-végpont a futó verziót és commitot mutatja | Működik; 52 új program-teszt és 3 felületi teszt; böngészőben 18 nézet 0 szabálysértéssel | [biztonsági leírás](docs/SECURITY.md) |
| **Mérés:** etalon-futás, determinizmus, közös kiértékelő riport, költségnapló | Működik | parancsok lent |

**Ismert korlátok:**
- A költségnapló és a keret csak a feldolgozón át futó úton él. A régi mérési parancsok a lezárt mérések összevethetősége miatt a korábbi módon hívnak.
- Egyszerre egy feldolgozó futhat (zár őrzi).
- A helyi szolgáltatásban nincs bejelentkezés: egyfelhasználós, saját gépes eszköz.
- A postafiók-letöltéshez futnia kell az Outlooknak; letöltés közben a feldolgozó irat-tételt nem dolgoz fel. A levél kép-csatolmányai (pl. aláírás-logó) nem kerülnek feldolgozásra.
- A 2026-09-28 előtti futásokhoz nincs keret, újrafuttatás után van (a régi OCR-eredmények szóadata pótlódik); a meglévő futás kerete a `reground` paranccsal újraszámolható.
- A közmű-költség riport csak a bruttó összeget bontja; a riport egy futásból készül (több futás összevonása még nincs).
- Néhány kezelő művelet (törlés, elrejtés, átnevezés, név- és mappalista) verzióellenőrzés nélkül fut; a mentés nincs titkosítva; a személyes adatnak még nincs megőrzési ideje. A nyitott biztonsági tételek: [biztonsági leírás](docs/SECURITY.md).
- Valós pontosságot független kézi etalon nélkül nem állítunk.

## Indítás

```powershell
uv venv --python 3.12 .venv; uv pip install -r requirements.lock   # részletek, OCR, kulcsok: docs/guides/SETUP.md
.\.venv\Scripts\Activate.ps1
python -m jav.cli hooks-install        # adatőr: commit és feltöltés előtti ellenőrzés (klónonként egyszer)
python -m jav.cli preflight            # teszt + kontraktus + konfig + git + adatőr + Ruff + állapotoldal
python smoke_test.py                   # kulcsok + egy élő JEV-hívás
```

Egy friss klónban a régi projekt (`10_AIFLOW_V4`) és az etalon nélkül a felület, a munkacsomagok és a futások működnek; az etalon-mérésekhez és a régi levél-bridge-hez a régi projekt kell. Részletek: [telepítés, friss klón](docs/guides/SETUP.md).

## Fő parancsok

```powershell
python -m jav.cli run <pdf> --arm S|G [--type invoice_foreign]      # egy számla a folyamaton, mentés az adattárba
python -m jav.cli golden --arm S|G [--type <csomag>] [--no-cache]  # etalon-futás (runs/*_golden_*.jsonl; a régi projekt etalonja kell)
python -m jav.cli determinism --arm S --n 5                        # ismételt futás gyorsítótár nélkül (régi projekt)
python -m jav.cli detect <pdf> | detect-golden | detect-corpus <mappa>   # a detect-golden a régi projektből
python -m jav.cli email <inbox/<mailbox>/<msgid>> | email-golden | email-inbox inbox/   # az email-golden a régi projektből
python -m jav.cli ocr [<pdf>]                                      # PDF nélkül: az OCR-motor állapota
python -m jav.cli eval-report [runs/*.jsonl]                       # közös kiértékelő riport a nyers futásokból, hívás nélkül
python -m jav.cli store | admin | configs | flows --check | docs   # adattár, vezérlőképernyő, konfigverziók, kontraktus, generált leírások
python -m jav.cli recipes | wp-create <mappa> | wp-assign <wp> invoice-extraction | wp-show <wp>   # munkacsomag és recept
python -m jav.cli run-start <wp> [--mode shadow|apply] | worker --once | run-show <run> | run-cancel <run> | run-approve <run> --actor <név>
cd ui; npm ci; npm run build; cd ..                               # a felület buildje (egyszer, és ui/src változás után)
.\scripts\dev.ps1 start | status | stop                          # felület + szolgáltatás: http://127.0.0.1:8930/ (végpontlista: /api/openapi.json) + feldolgozó
python -m jav.cli serve | worker-status | worker-stop              # ugyanez külön-külön
python -m jav.cli backup [--with-docs] | burr-prune                # adattár-mentés (a napi mentés beállítása: configs/service.json); a folyamatállapot-tár ritkítása
python -m jav.cli hooks-install | data-guard [--all]               # az adatőr bekapcsolása; a verziókövetett fa átnézése
python -m jav.cli calls-uncertain | calls-resolve <id> --note N    # bizonytalan kimenetű fizetős hívás kézi rendezése
burr                                                               # Burr-tracker: http://localhost:7241
```

Teljes lista: `python -m jav.cli --help`, illetve a [CLAUDE.md](CLAUDE.md) 5. pontja.

**Élő levélfogadás:** ajánlott a felület Postafiók nézete (048). A régi, kézi út (a régi projekt Outlook-bridge-ével, változatlanul; ez a régi projekt `data/` mappájába ír): előbb `python -m jav.cli email-ingest-server --port 8931 --run [--token <kulcs>]`, majd külön ablakban a bridge `-ApiToken <kulcs>` kapcsolóval. A fogadó 066 óta csak kulccsal fogad: `--token` (vagy a `JAV_INGEST_TOKEN` környezeti változó) nélkül indításkor egyszeri kulcsot ír ki; böngészőből érkező kérést elutasít.

```powershell
powershell -File C:\00_DEV_LOCAL\10_AIFLOW_V4\scripts\outlook_bridge.ps1 -RepoRoot C:\00_DEV_LOCAL\10_AIFLOW_V4 -OrchUrl http://127.0.0.1:8931/ingest/email -Accounts <smtp> -PeriodMode recent -SinceDays 30 -MaxItems 50 -AllEmails -ManualRun -NoArchive -WorkflowId email-intent -WorkflowVersion 1 -ApiToken <kulcs> [-Force]
```

## Szerkezet

| Hely | Tartalom |
|---|---|
| `jav/` | Python-csomag: folyamatok (`flow*.py`), jelöltkeresés, JEV/GPT-illesztés (`adapters/`), validátorok, adattár, OCR, kiértékelés, parancssor |
| `jav/experiments/`, `configs/experiments/` | lezárt és futó kísérletek; a futtató kód nem importálja őket |
| `configs/` | konfig mint adat: típus- és szándékregiszter, típuscsomagok, hívási helyek, küszöbök, modellek, OCR, a szolgáltatás határai és a mentés, receptek, adatkészletek, riportok, az adatőr ([leírás](docs/guides/CONFIGS.md)) |
| `ui/` | a böngészős munkafelület (React; build: `ui/dist/`, a szolgáltatás a gyökéren kiszolgálja) |
| `tests/` | offline tesztek (mesterséges adatokkal) |
| `scripts/` | a szolgáltatás indítója (`dev.ps1`), a napi mentés feladata, a Claude-horgok (`hooks/`), a git-horgok (`githooks/`, adatőr), egyszeri kísérleti szkriptek |
| `docs/` | kódtári dokumentáció (lásd lent); a belső munkaanyag ugyanitt, de a git nem követi |
| `runs/`, `store/`, `inbox/` | helyi futások, adattár, levelek — nincsenek gitben (PII) |

## Dokumentáció

A tárban lévő (kódtári) dokumentumok:

- [Felhasználói kézikönyv](docs/guides/USER_GUIDE.md): a munkafelület használata
- [Architektúra](docs/ARCHITECTURE.md) · [Biztonsági leírás](docs/SECURITY.md) · [Fogalomtár](docs/GLOSSARY.md) · [JEV-kézikönyv](docs/JEV_PLAYBOOK.md)
- [Dokumentációs szabvány](docs/guides/DOCUMENTATION.md) · [Fejlesztési munkamenet](docs/guides/DEVELOPMENT.md) · [Telepítés](docs/guides/SETUP.md) · [A beállítófájlok](docs/guides/CONFIGS.md)
- [Változáslista](CHANGELOG.md): a kiadások röviden
- Generált folyamatleírások: [docs/flows/](docs/flows/) (`python -m jav.cli flows`)
- [Claude-utasítások](CLAUDE.md): állandó munkaszabályok a fejlesztő modellnek
- TypeSafe/JEV hivatalos dokumentáció: [docs.typesafe.ai](https://docs.typesafe.ai/llms.txt)

Helyben, a git nélkül (belső munkaanyag, [dokumentációs szabvány](docs/guides/DOCUMENTATION.md)):
- a belső belépő oldal (`docs/INDEX.md`): aktuális terv, jelentések jegyzéke;
- a teendőlista, a döntésnapló és az útiterv;
- a tervek, jelentések és átadók;
- a generált oldalak: az állapotoldal (`docs/STATE.md`) és a hívásihely-katalógus (`docs/callsites/`, `python -m jav.cli docs`).
