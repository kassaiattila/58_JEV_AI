# A beállítófájlok leírása

**Érvényes:** 2026-09-30-tól (071, v1.0.5). **Kinek szól:** a fejlesztőnek és a rendszert beállító felhasználónak.

## Laikus összefoglaló

A rendszer minden hangolható része beállításfájlban van, nem a programkódban. Ilyen az irattípusok és a levélszándékok leírása, a mesterséges intelligenciának feltett kérdések, a döntési küszöbök, a modellek és áraik, a receptek költségkerete és a helyi szolgáltatás korlátai. Minden fájlnak van verziószáma és változásnaplója, a tartalmából számolt ujjlenyomat pedig minden fizetős hívás naplósorába bekerül, így egy mérés mindig visszavezethető arra, milyen beállításokkal futott. Ha a modellnek szóló kérdés vagy leírás változik, a következő mérés újra fizetős hívásokkal megy, ezért előtte költségkeretet kell kérni; a küszöbök, a korlátok, a keretek és egy új folyamat bekapcsolása a felhasználó döntése. A futó szolgáltatás és a feldolgozó a beállításokat csak induláskor olvassa be, ezért módosítás után újra kell indítani őket.

## 1. Közös szabályok

A beállításfájl a „konfig mint adat” elvet valósítja meg ([fogalomtár](../GLOSSARY.md)): a program a mechanizmus, a fájl a paraméter. Egy beállítás módosítása így fájlszerkesztés és mérés, nem programozás, és minden módosításnak nyoma marad.

1. **Formátum.** JSON, UTF-8, LF sorvég (Pythonból `encoding="utf-8"`-tel írva). Minden fájl `meta` blokkal kezdődik: `name`, `version` (háromrészes, például `1.4.0`) és `changelog` (bejegyzésenként `version`, `date`, `note`). A betöltő (`jav/cfg.py`) a verzió nélküli fájlt elutasítja.
2. **Ujjlenyomat (`config_hash`, a továbbiakban hash).** A hash a fájl tartalmának rövidített sha256-a (16 hexa jegy). A változásnapló nem része, ezért egy megjegyzés nem változtatja meg; a verziószám viszont része. A hash a folyamatok minden JEV- és GPT-hívásának hívásnapló-sorába bekerül, a hívás összes beállítás-bemenetével együtt: hívási hely, regiszter vagy típuscsomag, a csomag utasítás- és sémafájlja.
3. **Mikor lesz fizetős az újramérés.** A JEV-gyorsítótár kulcsát a konkrét modellverzió, a küldött állapot és a kérdések adják; a hash nincs benne. Ezért bármely változás a kérdésben, az instrukcióban, a szószedetben vagy egy választási lehetőség leírásában (`what` / `not_for` / `examples`) új kulcsot ad, és a következő golden-futás élő, fizetős hívásokkal megy. A puszta verziólépés, a felirat és a küszöb változása nem jár új hívással (az OCR kivétel, lásd 3. szakasz). A GPT-kivonatnak nincs válasz-gyorsítótára, a G-út minden futása fizetős.
4. **A tartalmi változás menete** (CLAUDE.md 4. pont):
   - a `meta.version` lép (szokás szerint javításnál a harmadik, bővítésnél a második szám), és a `changelog` végére új bejegyzés kerül a körrel és az okkal;
   - lefutnak az érintett tesztek;
   - ha a modellnek szóló szöveg változott, golden-futás jön az érintett folyamaton;
   - a `python -m jav.cli docs` újragenerálja a helyi hívásihely-katalógust és a folyamatleírásokat;
   - a szolgáltatást és a feldolgozót újra kell indítani (3. szakasz).

   Élő, fizetős mérés csak előre jóváhagyott részkerettel, tiszta munkafán, a commit hash rögzítésével indulhat.
5. **Felhasználói döntés kell** (CLAUDE.md 1. és 2. pont): küszöbhöz és útvonalhoz, a típus- és szándékkészlethez (típushatár), költségkerethez, a helyi szolgáltatás korlátaihoz, új folyamat vagy fizetős lépés bekapcsolásához. A döntés dátummal a döntésnaplóba kerül. Fájlonként a 2. szakasz „Döntés kell?” oszlopa mutatja.
6. **Személyes adat** beállításfájlba sem kerülhet, példának kitalált érték kell. Ha egy kitalált adószám vagy bankszámlaszám ellenőrzőszáma helyes, az értéket az adatőr kivétellistájára kell felvenni ([fejlesztési munkamenet](DEVELOPMENT.md), 1. szakasz).

## 2. A felső szintű fájlok (`configs/*.json`)

Minden sorban kötelező a verziólépés és a változásnapló-bejegyzés; a „Változás után” oszlop az ezen felüli teendőt mutatja. Az „újraindítás” jelentése: `.\scripts\dev.ps1 stop`, majd `start`, ha a szolgáltatás fut.

| Fájl | Szerep | Ki olvassa | Változás után | Döntés kell? |
|---|---|---|---|---|
| `capability_catalog.json` | A típus- és szándékkészlet elvárt listája: melyik részletes típusnak és szándéknak kell léteznie, melyik régi szándék kivezetett. Hívás nélküli lefedettség-ellenőrzés. | `jav/capability_catalog.py` | `python -m jav.capability_catalog`; `pytest tests/test_capability_catalog.py` | A típus- és szándékkészletről hozott döntést követi |
| `data_guard.json` | Az adatőr szabályai: tiltott útvonalak és kiterjesztések, adatminták, a kitalált értékek kivétellistája (`allow`, `allow_why`), a tűrt saját adat (`known`) és a tiltott kifejezések (`deny`) csak sha256-tal, a fel nem tölthető régi történet (`forbidden_history`). | `jav/data_guard.py` (commit- és feltöltés előtti horog) | A következő commitnál él; a teljes fa átnézése: `python -m jav.cli data-guard` | `allow`: nem, de indoklással; `known`, `deny`, `forbidden_history`: igen |
| `datasets.json` | Az adatkészletek felsorolt értékeinek magyar feliratai (állapotok, módok, következő lépés), a futás-adat gyorsítótárának mérete, a letöltés sorkorlátja. | `jav/datasets.py`, `jav/export.py`, `jav/mailbox.py` | újraindítás | Nem |
| `doc_types.json` | Az irattípus-regiszter (M1): durva kategóriák `what / not_for / examples / parent` leírással, szülő-családok, ismeretlen típus; az `old_type_map` a részletes típust a durva kategóriához rendeli. | `jav/doc_types.py`, `jav/detect.py`, `jav/capability_catalog.py` | `detect-golden` (új kulcs, élő hívások), `detect-determinism`; `docs`; újraindítás | Igen (típushatár, osztálykészlet) |
| `email_tasks.json` | A feladatjavaslat akciókészlete, bizonyíték-szabályai és hosszkorlátai. A GPT-utasítás a `jav/prompts/email_tasks_prompt.md` fájlban van, a hash azt is fedi. | `jav/email_tasks.py`, `jav/datasets.py`, `jav/export.py`, felület | újraindítás; `cd ui; npm run build` | Az akciókészlethez igen, a korlátokhoz nem |
| `field_labels.json` | A mezők, a listaoszlopok és az irattípusok magyar neve a felületen és a letöltésekben. | `jav/datasets.py`, `jav/export.py`, `jav/mailbox.py`, felület | `pytest tests/test_field_labels.py`; újraindítás; `npm run build` | Nem |
| `grounding.json` | A forráshely-keresés címkeszótára (mezőnként a nyomtatott címkék) és távolsági tűrései. | `jav/grounding.py` | `pytest tests/test_grounding.py`; újraindítás; a gépi forráshely az új futásokon változik, a meglévőkön a `python -m jav.cli reground` számolja újra (AI-hívás nélkül); a javított mező helyét a felület megnyitáskor újra keresi | Nem |
| `intents.json` | Az e-mail-szándék regisztere (M3): szándékok `what / not_for / examples / parent` leírással, családok, egyéb szándék. | `jav/intents.py`, `jav/intent.py`, felület | `email-golden` (élő), `email-determinism`; `docs`; újraindítás; `npm run build` | Igen (osztálykészlet) |
| `models.json` | JEV-alias és GPT-modell, árlista, időkorlát, újrapróbálás, a JEV-gyorsítótár verziója, az alias-feloldás érvényessége, a Burr-projektnevek. | `jav/config.py` (közvetlenül, induláskor), `jav/adapters/jev.py`, `jav/admin.py` | A `cache_version` léptetése minden gyorsítótár-kulcsot érvénytelenít (minden hívás élő lesz); ár nélküli GPT-modellt a keret nem enged hívni; újraindítás | Modellcseréhez és gyorsítótár-verzióhoz igen; az ár a szolgáltató árlistáját követi |
| `ocr.json` | Az OCR-lánc: motor, felbontás, oldalkorlát, a tesseract beállítása és helye, a régi Docker- és Azure-út, valamint a fizetős Azure-eszkaláció kapcsolója. | `jav/ocr.py` | `python -m jav.cli ocr` (a motor állapota); minden irat újra OCR-en megy (3. szakasz); újraindítás | Az eszkaláció bekapcsolásához (fizetős) igen |
| `policy.json` | A döntési szabályok: sávok és küszöbök (`bands`, `band_for`), OCR-minőség és eszkalációs küszöb, az e-mail útvonalai, a részletes típus horgony-rése, az „egyik sem” címke (`none_label`). | `jav/policy.py`, `jav/eval_report.py`, `jav/admin.py` | Nem kell újrafuttatni: az `eval-report` a nyers futásokból ingyen mutatja, hány eset váltana sávot; újraindítás. Kivétel a `none_label`, mert választási lehetőségként a kérdésbe kerül | Igen |
| `recipe_help.json` | A receptek és beállításaik magyarázó szövege (Receptek oldal, Recept-kártya). Külön fájl, hogy a szöveg javítása ne jelezzen receptváltozást. | `jav/work_views.py` | `pytest tests/test_recipe_help.py`; újraindítás | Nem |
| `recipes.json` | A folyamatreceptek: lépések, bemenet, paraméterek, tételenkénti költségkeret szolgáltatónként (`max_item_usd`, `max_item_usd_by_kind`, `param_item_usd`), próbálkozásszám. Minden recept saját `version`-t is visel. | `jav/work.py`, a feldolgozó a futás receptmásolatán át | A recept saját `version`-je is lép; a meglévő hozzárendeléseken „a recept változott” figyelmeztetés jelenik meg; újraindítás | Igen (keret, új recept, alapbeállítás) |
| `reports.json` | A közmű-költség riport mezői és a letöltés formája (CSV-elválasztó, a képletnek látszó cellák előtagjai). | `jav/report_utility.py`, `jav/export.py` | újraindítás; a képlet-védelem listája nem szűkíthető | Nem |
| `service.json` | A helyi szolgáltatás: cím és port, engedett gépnevek, kérésméret, mappakorlát és engedett gyökerek, a fejlesztői felület címe, a bizonyosság-sáv megjelenítési határai, bemeneti korlátok, napi mentés (időpont, megőrzés, a második mentési hely, például egy hálózati meghajtó). | `jav/api.py`, `jav/pdf.py`, `jav/ocr.py`, `jav/backup.py`, `scripts/backup-task.ps1` | újraindítás; a mentés időpontjához `.\scripts\backup-task.ps1 install` | Igen (korlátok, mappák, mentés) |

A `python -m jav.cli configs` lista ezek mellett a hívási helyeket (`callsite:<név>`) és a típuscsomagokat (`type:<kulcs>`) is sorolja. Az alap-csomag, a kísérletek és a régi típus-másolatok nincsenek benne (5–7. szakasz).

## 3. Mikor lép életbe a változás

A helyi szolgáltatás és a feldolgozó minden beállításfájlt az első használatkor egyszer olvas be, és a folyamat végéig emlékezetben tartja; futás közben nem olvassa újra. A parancssori parancsok minden indításkor friss állapotot látnak.

| Hol | Mikor látja a változást |
|---|---|
| Helyi szolgáltatás és feldolgozó | Újraindítás után (`.\scripts\dev.ps1 stop`, majd `start`). |
| Már elindított futás | A recept és a keretfoglalás az indításkor rögzül (konfigurációs pillanatkép), a receptváltozás nem hat rá. A típuscsomagot, a kérdéseket és a küszöböket a feldolgozó a saját indulásakor olvasta be, és azokkal dolgozik. |
| Felület | A `field_labels.json`, az `intents.json` és az `email_tasks.json` a felület buildjébe épül: `cd ui; npm run build`, utána frissíteni kell a böngészőt. |
| Parancssor (golden, `configs`, `backup`) | Azonnal, minden indításkor. |
| Adatőr (git-horgok) | A következő commitnál vagy feltöltésnél. |
| Napi mentés | A mentés naponta új folyamatként indul, és a `backup` szakaszt magától olvassa. Csak az **időpont** változásához kell a feladatot újratelepíteni: `.\scripts\backup-task.ps1 install`. |
| OCR-gyorsítótár | A kulcsban az `ocr.json` hash-e is benne van: bármely változás után (a puszta verziólépés után is) minden irat újra OCR-en megy. Bekapcsolt eszkalációnál ez fizetős Azure-oldalakat is jelenthet. |

## 4. Hívási helyek (`configs/callsites/`)

A hívási hely ([fogalomtár](../GLOSSARY.md)) a folyamat egy pontja, ahol a JEV-et kérdezzük. A fájlja mindazt tartalmazza, amit a modell a kérdésből lát: az angol instrukciót és szószedetet, a választási lehetőségek leírását, az igen/nem kérdéseket, a jelenlét-kérdés mintáját, az állapotba kerülő sorok számát, valamint a kérés-méret keretet. Ezért a fájl bármely szöveges változása új gyorsítótár-kulcsot ad: a következő golden-futás és minden új futás élő, fizetős hívással megy. Az írás szabályai a [JEV-kézikönyvben](../JEV_PLAYBOOK.md) és a CLAUDE.md JEV-ellenőrzőlistájában vannak.

| Fájl | Mit kérdez | Ki olvassa | Mérés változás után |
|---|---|---|---|
| `detect.json` | Durva irattípus (Choice a regiszter fölött), magyar-e a kiállító, nyelv (M1) | `jav/detect.py` (hash a regiszterrel együtt) | `detect-golden`, `detect-determinism` |
| `detect_detail.json` | Részletes típus a durva kategórián belül, ha a horgony-pontszám nem dönt; a lehetőségek a típuscsomagok leírásai | `jav/detect_detail.py` (hash az összes típuscsomaggal együtt) | `detect-golden` |
| `email_intent.json` | Levélszándék (Choice), jelzések (Noul), sürgősség (Score), beszúrt utasítás (M3) | `jav/intent.py` (hash a szándékregiszterrel együtt) | `email-golden`, `email-determinism`, `email-injection-probe` |
| `select.json`, `select_foreign.json`, `select_utility.json` | S-út: mezőnkénti választás a kód jelöltjei közül, jelenlét-kérdéssel, kérésekbe csoportosítva | `jav/jev_select.py` (hash a típuscsomaggal együtt) | `golden --arm S --type <kulcs>`; előtte ingyenes `recall` |
| `verify.json`, `verify_<kulcs>.json` | G-út: hibajelzések (Noul) a GPT-kivonat mezőire | `jav/jev_verify.py` (hash a típuscsomaggal együtt) | `golden --arm G --type <kulcs>`, `verifier-probe` |

- A típuscsomag `select_callsite` és `verify_callsite` mezője nevezi meg, melyik hívási helyet használja.
- A `verify_<kulcs>.json` az `"inherits": "verify"` mezővel örökli a közös hibakérdéseket, és főként a típus mezőleírásait (`field_specs`), szószedetét és kérés-méret keretét adja hozzá. A régi projektből átvett típusok ellenőrző hívási helyei így készültek (`jav/typepack_convert.py`).
- A `request_char_budget` és az `option_context_max` a kérés-méret keret ([fogalomtár](../GLOSSARY.md)): túl nagy kérésnél a kód előbb a szöveget, aztán a leírásokat, végül a jelöltek számát szűkíti.

## 5. Típuscsomagok (`configs/types/`)

A típuscsomag ([fogalomtár](../GLOSSARY.md)) egy dokumentumtípus adatkinyerésének minden típusfüggő adata. Megadja, milyen mezők vannak és milyen fajtájúak, melyik kötelező, magas tétű vagy csak tájékoztató, milyen ellenőrzések futnak, melyik úton fusson a kinyerés, és melyik kérdéskészletet használja. A kinyerő folyamat típusfüggetlen, ezért új típushoz új csomag kell, nem új program, amíg a meglévő mező-fajták elegendők. A betöltő (`jav/typepack.py`) ellenőrzi a fajtákat és a listák mezőneveit, eltérésnél hibát ad.

| Kulcs | Szerep |
|---|---|
| `document`, `parent`, `detect`, `auto_detect` | Leírás (egyben a részletes típus kérdésének egyik lehetősége); durva kategória a regiszterből; a horgony-pontszám kulcsszavai (`required_any`, `supporting`, `excluders`); részt vesz-e az automatikus részletes felismerésben |
| `fields`, `list_fields`, `enums` | Mező → mező-fajta; a tételes listák oszlopai; a felsorolt értékek |
| `scored_fields`, `informational_fields`, `required`, `high_stakes` | Pontozott, csak tájékoztató, kötelező és magas tétű mezők; ezekből számolódik a sávvizsgálat és a jelenlét-kérdések köre |
| `validators`, `text_labels` | Kódos ellenőrzések (`"review": false` = csak jelző ellenőrzés); a szabad szöveges mezők címkéi |
| `candidate_profile`, `arms`, `default_arm` | Jelölt-profil (`hu`, `intl`, `utility`); a futtatható utak; az ajánlott út |
| `select_callsite`, `verify_callsite` | A két hívási hely neve (S-út nélküli csomagnál az első `null`) |
| `prompt_file`, `schema_file` | A G-út utasítása és kimeneti sémája a `jav/prompts/` alatt; a csomag hash-e ezek tartalmát is fedi |
| `golden_type_key`, `extends` | Az etalon típusneve a régi projektben; az örökölt alap-csomag neve |

**Öröklés.** Az `extends` mezővel a csomag egy alap-csomagot örököl a `configs/types/_base/` alól ([fogalomtár](../GLOSSARY.md): alap-csomag). Az alap mezői, listái, ellenőrzései és sémája a gyermekéi elé kerülnek; ma a magyar közmű-számlák közös része ilyen. Az alap-csomag önmagában nem futtatható, és a `configs` listában sem szerepel, de a gyermek hash-e lefedi.

**Változás után:** `golden --arm S|G --type <kulcs>` ott, ahol van etalon (a régi projektből átvett típusokhoz csak mesterséges minta van); az S-útnál előtte ingyenes `recall`. A leírás és a mezőlisták a kérdésbe is bekerülnek, ezért módosításuk új gyorsítótár-kulcsot adhat.

**Új típus felvétele** (külön útmutató még nincs):

1. csomag: `configs/types/<kulcs>.json`, `meta` blokkal, szükség esetén `extends`-szel;
2. utasítás és séma: `jav/prompts/<kulcs>_prompt.md` és `<kulcs>_schema.json`;
3. ellenőrző hívási hely: `configs/callsites/verify_<kulcs>.json` (`"inherits": "verify"`), S-úthoz választó hívási hely is;
4. magyar név minden mezőnek és listaoszlopnak a `field_labels.json`-ban (a `tests/test_field_labels.py` jelez, ha hiányzik);
5. leltár: `doc_types.json` → `old_type_map` és `capability_catalog.json` → `expected_document_keys`, különben a leltár hibát ad;
6. tesztek csak mesterséges adattal, utána `python -m jav.cli docs`;
7. amíg a felhasználó nem döntött a típushatárról, `"auto_detect": false`, vagyis a típus nem kerül be az automatikus felismerésbe.

## 6. Kísérletek (`configs/experiments/`)

Lezárt és futó képességpróbák beállításai és mesterséges esetei: állítás-értékelés, forráskeresés, beszúrt utasítás, tanulási ágak és hasonlók. A formátumuk nem egységes: van, amelyiknek `meta` blokkja van, van, amelyik felső szintű `version` mezőt használ. A `configs` lista és a közös hash nem fedi őket; a kísérleti kód a saját forrás-ujjlenyomatait a nyers futásban rögzíti. A kísérleti kód (`jav/experiments/`) és néhány, külön parancsból futó tanulási vagy próbamodul olvassa őket (`jav/document_learning.py`, `jav/document_chunks.py`, `jav/claim_assessment.py`, `jav/source_find.py`); a helyi szolgáltatás és a feldolgozó nem. Módosításuk ezért a munkacsomagok futására nem hat. Fizetős próbához előre jóváhagyott részkeret kell (néhány fájlban saját költséghatár is áll, például `budget_usd`), esetleírás pedig csak mesterséges vagy anonimizált adattal készülhet.

## 7. Régi típus-másolatok (`configs/legacy_types/`)

A régi projekt típusmappáinak szó szerinti másolata típusonként: séma, utasítás, szabályok, felismerési kulcsszavak és a régi leíró adat. Mellettük egy `manifest.json` áll a forrás útvonalával és minden fájl sha256-jával. Néhány mappában `fixtures/synth_*.json` is van, ezek kizárólag mesterséges minták. Olvasói:

- `jav/legacy_packs.py`: betöltéskor ellenőrzi az ujjlenyomatokat, eltérésnél hibát ad;
- `jav/legacy_runtime.py`: a tanulási ág régi séma szerinti kivonata;
- `jav/capability_catalog.py`: lefedettség;
- `jav/typepack_convert.py`: az egyszeri átalakító, amely ezekből készítette a megfelelő típuscsomagokat és ellenőrző hívási helyeket.

Ezeket nem szerkesztjük, mert forrásmásolatok. A viselkedést a belőlük készült típuscsomagban vagy hívási helyben kell módosítani. Nincs `meta` blokkjuk, a `configs` listában nem szerepelnek, és az automatikus útválasztás ki van rájuk kapcsolva (`automatic_routing_enabled: false`).

## 8. Ellenőrzés

- `python -m jav.cli configs`: minden felső szintű fájl, hívási hely és típuscsomag neve, verziója, hash-e és utolsó változásnapló-bejegyzése. A verziót és a hash-t itt kell nézni, ez a leírás szándékosan nem sorolja fel őket. A `python -m jav.cli admin` ugyanezt a modellekkel és az árakkal együtt mutatja; a helyi, generált állapotoldal is tartalmazza.
- `python -m jav.cli preflight`: a „konfigok” sor ugyanezt listázza. A betöltési hiba (rossz JSON, hiányzó verzió) itt és a tesztekben derül ki.
- Tesztek: `tests/test_cfg.py` (minden fájl betölthető, a verzió háromrészes, a változásnapló nem üres, a hash stabil, és a változásnapló nem hat rá), `tests/test_field_labels.py`, `tests/test_capability_catalog.py`, `tests/test_recipe_help.py`, `tests/test_encoding_guard.py` (rossz kódolással visszaírt ékezet).
- Új felső szintű beállításfájl felvételekor a 2. szakasz táblázatát kézzel kell bővíteni, ezt ma teszt nem ellenőrzi.

A változtatások teljes rendje (mit követ melyik mérés): [architektúra](../ARCHITECTURE.md), 4. szakasz „Hangolás és változtatás”. A telepítés és a mappakorlát leírása: [telepítés](SETUP.md).
