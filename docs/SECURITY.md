# Biztonsági leírás

**Érvényes:** 2026-09-30-tól (071, v1.0.5). **Kinek szól:** a felhasználónak és a fejlesztőnek.

## Laikus összefoglaló

A rendszer egy gépre és egy felhasználóra készült. A helyi szolgáltatás csak a saját gépről fogad kérést, az idegen weboldalról vagy idegen gépről jövőt elutasítja, és a böngészőnek is megtiltja, hogy a felületet más oldalba ágyazza, vagy az irat-adatot a lemezére mentse. A fizetős AI-hívások előre lefoglalt költségkeretből mennek, minden hívás a hívásnaplóba kerül, és semmi nem válik érvényessé emberi jóváhagyás nélkül. A GitHubra csak kód és kódtári leírás kerülhet: az adatőr (commit és feltöltés előtti ellenőrzés) megállítja a műveletet, ha személyes adat, kulcs vagy belső munkaanyag kerülne fel. A gyenge pontok is ismertek: nincs valódi belépés, a személyes adat titkosítás és megőrzési idő nélkül áll a gépen és a mentésekben, a rejtett utasítások elleni védelmet pedig csak kis mintán mértük (9. pont); ezért a rendszer hálózaton nem tehető elérhetővé.

A szakszavak jelentése a [fogalomtárban](GLOSSARY.md) van.

## 1. Kitől és mitől véd a rendszer

**A határ:** egy gép, egy Windows-fiók, egy felhasználó (vagy néhány ember felváltva, ugyanazon a gépen). A helyi szolgáltatás csak a gép belső címén figyel; más címmel a program el sem indul.

**Mitől véd:**
- a böngészőben közben megnyitott idegen weboldal ne tudjon műveletet indítani a helyi szolgáltatásban;
- egy idegen webcím, amelyet a támadó a gép belső címére irányít, ne érje el a szolgáltatást;
- egy óriási kérés vagy irat ne fogyassza el a gépet;
- a fizetős hívás ne lépje túl a futás keretét, és ne induljon kétszer;
- az iratba vagy levélbe rejtett utasítás ne fogadtasson el csendben rossz adatot;
- személyes adat, kulcs vagy belső munkaanyag ne kerüljön a GitHubra.

**Mitől nem véd:**
- a gépen futó más programtól és ugyanannak a Windows-fióknak más használójától: ezek elérik a helyi szolgáltatást és a fájlokat is;
- a gép vagy a hálózati tároló ellopásától: a rendszer semmit nem titkosít (7. pont);
- attól, hogy valaki más nevében dolgozzon: nincs jelszó.

**A névválasztás nem azonosítás.** A „Ki dolgozik?” mezőben kiválasztott név (aktív felhasználó) csak azt rögzíti, ki mit csinált. A névlista jelszó nélkül olvasható, és aki a gépen eléri a szolgáltatást, bármelyik listán szereplő névvel küldhet kérést. A naplóban álló név ezért nem bizonyítja, ki ült a gépnél.

**Hálózati használatnál** (ma a kód nem engedi): bárki bármelyik névvel dolgozhatna; a mappakorlát alapból ki van kapcsolva, így a gép bármely létező mappájából vehetne fel iratot, és megnyithatná; a beállítások mentésénél pedig az utolsó mentés nyer. Mielőtt a szolgáltatás a gépen kívülről is elérhető lenne, ezeket a 9. pont tételeivel meg kell oldani.

## 2. A helyi szolgáltatás kapuja

A helyi szolgáltatás a felület és a parancssor közös kapuja. Minden kérést ellenőriz, mielőtt bármi történne:

- **Csak a gép belső címe.** Más címmel hibát ad, és el sem indul.
- **Gépnév-ellenőrzés.** Csak a gép saját nevére szóló kérést fogad el. Ez véd az ellen, hogy egy idegen webcím a gép belső címére mutasson.
- **Eredet-ellenőrzés.** Ha a kérés böngészőből jön, a küldő oldal címének pontosan egyeznie kell a szolgáltatás saját címével vagy a beállított fejlesztői felület címével. Más helyi port és az üres eredet is elutasítva (2026-09-29 óta pontos egyezés).
- **Író kérés csak JSON-ban.** Létrehozás, módosítás, törlés csak ebben a formában jöhet, így egy idegen oldal egyszerű űrlapja nem indíthat műveletet. A kérés legfeljebb 256 KB, darabolt küldésnél is.
- **Szerkezet-ellenőrzés.** Ismeretlen mező, rossz alakú azonosító vagy túl hosszú szöveg esetén a kérés elutasítva.
- **Név minden emberi döntéshez.** Futás indítása, jóváhagyás, javítás, recept, csomag módosítása, a feldolgozó leállítása és a mentés név nélkül nem megy. Ha a Felhasználók listája nem üres, csak a listán szereplő névvel.
- **Forrásirat csak a csomagból.** Az irat képét és forrásfájlját csak akkor adja ki, ha az a munkacsomagba felvett, azóta változatlan fájl. Más fájl ezen az úton nem olvasható ki.
- **A kattintható végpontlista ki van kapcsolva** (a felhasználó döntése, 2026-09-30). Ez a lap külső tárhelyről töltött volna be programkódot, amely a helyi címen, a felület jogával futott volna. A gépi végpontlista megmaradt.

## 3. Böngészős védőfejlécek (2026-09-30 óta)

A helyi szolgáltatás minden válaszához utasítást fűz a böngészőnek, a hibás és az elutasított kérés válaszához is. Ez a 2. pont védelmei mögötti második réteg:

- a felület nem ágyazható be más oldalba, így egy idegen oldal nem tudja láthatatlanul a sajátja alá tenni, és eltéríteni a kattintásokat;
- a felület csak a saját fájljait töltheti be és futtathatja: külső program, stíluslap és betűkészlet nem; a beágyazott kép, betűkészlet és a letöltés a saját adatából megengedett;
- a böngésző nem találgathatja a fájl típusát, nem adja tovább a felület címét más oldalnak, és más oldal nem töltheti be a szolgáltatás válaszait;
- az irat-adatot hordozó válaszok (adatok, oldalkép, forrásirat, letöltés) nem kerülhetnek a böngésző lemezes gyorsítótárába; az oldalkép korábban egy napig ott maradt;
- a forrás-PDF a böngésző saját PDF-nézőjében nyílik, ezért ott csak a beágyazás tiltott (a szigorúbb szabály a nézőt is letiltaná);
- a felület programfájljai gyorsítótárazhatók, mert irat-adat nincs bennük.

## 4. Bemenet: iratok, mappák, méret

- **Bemeneti korlát** minden belépési ponton (felület, parancssor, feldolgozó): 100 MB-nál nagyobb vagy 300 oldalnál hosszabb iratot a szövegkinyerés nevesített hibával megállít. A 40 megapixelnél nagyobb oldal képe kisebb felbontással készül, szövegfelismerés nem fut rá, a tétel teendőt kap.
- **Mappák.** 2026-09-28 óta a felhasználó döntése szerint bármely létező helyi mappa vagy fájl megadható. A mappakorlát egy beállítással visszakapcsolható; ekkor csak a megadott gyökérmappák alatti hely fogadható el. Az útvonalat a szolgáltatás a hivatkozások követésével feloldja, és csak létező mappát vagy fájlt fogad el.
- **Figyelt mappa.** A feldolgozó csak olvassa; az új iratokból munkacsomag lesz, de fizetős futás nem indul magától.
- **Rögzített bemenet.** Ha egy fájl a felvétele után megváltozik, a futás nem dolgozza fel, hanem hibát jelez.

## 5. AI-hívások

**Költség.** Minden fizetős hívás előtt a rendszer a legrosszabb esetre becsült összeget lefoglalja a futás keretéből (költségfoglalás). Ha nem fér bele, a hívás el sem indul, és a tétel teendőt kap. A hívásnapló minden hívást a hívás előtt rögzít, utána a tényleges modellel és költséggel zárja; a sikertelen hívás is benne van. Az ismeretlen költségű hívás a legnagyobb összeggel számít. A bizonytalan kísérletet a rendszer nem ismétli meg magától, mert kétszer fizetnénk. Ha a beállított GPT-modellnek nincs ára az árlistán, keret alatt nem hívjuk, mert a foglalás nullát látna.

**Kulcsok.** A szolgáltatói kulcsok a gép helyi kulcsfájljában vannak. Ezt a git nem követi, és az adatőr a feltöltés előtt a kulcsok értékét is keresi. A JEV programcsomagjának részletes naplója a kérés teljes szövegét, vagyis az irat tartalmát is kiírná, ezért a rendszer ezt csak kifejezett engedéllyel hagyja bekapcsolva.

**Rejtett (beszúrt) utasítás.** A beszúrt utasítás olyan mondat egy iratban vagy levélben, amely nem az embernek, hanem a feldolgozó rendszernek szól. A védelem több rétegű:
- **S-úton** a JEV csak a kód által az iratból kigyűjtött jelöltek közül választhat; új értéket nem írhat.
- **G-úton** a GPT-kivonat minden mezőjét a JEV külön kérdéssel ellenőrzi, az adószámot és a bankszámlaszámot a kód ellenőrzőszámmal is.
- **Levélnél** külön jelzés figyeli a beszúrt utasítást. Ha határozott (igen-sáv), a levél minden más útvonal előtt gyanúsként kézi ellenőrzésre kerül, és feladatjavaslat sem készül rá.
- **Feladatjavaslat:** minden állításához szó szerinti idézet kell a levélből, a kitalált határidő vagy felelős kiesik. Alapból ki van kapcsolva, és csak ember fogadhatja el.
- **Jóváhagyás:** éles futás csak akkor hagyható jóvá, ha minden tétele lezárult, és nincs nyitott teendő.
- **Ami még hiányzik:** az irat-utasításokban nincs „a forrásszöveg adat, nem utasítás” védőmondat, és iratoknál nincs külön beszúrt-utasítás jelzés (9. pont).

**Mért eredmény** (kis próbák, nem általános bizonyíték):
- **Iratok, 2026-09-29.** 3 kitalált magyar számla, tiszta és négy támadó változatban: a fizetendő összeg „átírása”, bankszámla-csere egy másik érvényes számra, „ne tedd teendőre”, „ez nem számla”. Mindegyiken lefutott a típusfelismerés, az S-út és a G-út. A 24 kinyerésből (3 számla, a tiszta és az adatot célzó három támadó változat, mindkét úton) egyben sem fogadott el a rendszer rossz értéket teendő nélkül. A bankszámla-cserénél az S-út mindháromszor az igaz számot választotta, de bizonytalanul, ezért teendőt adott. Az „ez nem számla” mondat mellett mind a 3 irat számla maradt, alacsonyabb bizonyossággal. A próba változatonként egy megfogalmazással és egy futással készült, valódi iraton nem mértük. A nyers futás helyben, a futások mappájában van.
- **Levelek, 2026-09-20.** 8 etalon levél tisztán és négy beszúrt változatban. A tiszta levelek egyikén sem jelzett tévesen (0 a 8-ból). A levél elejére tett utasítást (magyarul és angolul, három megfogalmazásban) mind a 24 esetben jelezte, és a levél kézi ellenőrzésre került. A levél legvégére tett angol utasítást viszont 8-ból csak 5-ször jelezte. A felismert szándékot a beszúrt mondat a 40 esetből egyszer sem változtatta meg. A próbát azóta nem ismételtük; a kérdés szövege azóta nem változott. A nyers futás helyben van.

## 6. Levelek és postafiók

- **Postafiók-letöltés:** a gépen futó Outlookon át, a régi Outlook-szkripttel történik. A rendszer postafiók-jelszót nem kér és nem tárol.
- A letöltés idejére egy saját, csak a gép belső címén figyelő fogadó indul, egyszer használatos véletlen kulccsal. A letöltés végén leáll.
- A postafiók-címet és a mappanevet a rendszer ellenőrzi, mielőtt a szkriptnek átadná: idézőjel, pontosvessző, dollárjel és hasonló, parancsként értelmezhető jel nem lehet benne.
- **Az önálló levélfogadó** (a régi szkripthez, parancssorból indítva) csak kulccsal fogad. Ha nincs beállított kulcs, induláskor véletlen kulcsot kap, és kiírja. A böngészőből jövő kérést (eredet-fejléccel, nem JSON-törzzsel vagy idegen gépnévvel) elutasítja. A kérés legfeljebb 2 MB, a szerkezetét ellenőrzi.
- A fogadó a postafiók mappanevét maga képzi, és semmit nem ír a bejövő mappán kívülre. A csatolmány csak a bejövő adatok gyökere alatti, létező fájlra mutathat.
- Az azonos tartalmú ismétlés nem íródik felül, és nem indít új futást. A megváltozott tartalom új változatként kerül a régi mellé.

## 7. Személyes adat a gépen

A rendszer semmit nem titkosít. A lemez titkosítása (BitLocker) a gép beállítása, az állapotát még nem ellenőriztük. **Megőrzési idő nincs:** az alábbi adat korlátlan ideig marad, kivéve, ahol a táblázat mást mond.

| Hely | Mi van benne | Mennyi marad |
|---|---|---|
| Adattár | iratok és levelek kinyert adatai, az iratok szórétege, javítások, teendők, futások, hívásnapló | korlátlan |
| Folyamatállapot-tár | a feldolgozás teljes állapota tételenként, benne a beolvasott szöveg | lezárt tételnél csak az utolsó mentés (ritkítás) |
| Futások mappája | nyers futások; a JEV-gyorsítótár (a kérésekkel együtt irat- és levélszöveg-részletek); az OCR-gyorsítótár (felismert szöveg) | korlátlan |
| Üzemi napló | hibák hibanyommal, benne fájlnév és útvonal is lehet; egyes műveleteknél a kérő neve | 5 MB-onként forog, 5 régi példány marad |
| Bejövő levelek mappája | a letöltött levelek szövege és fejlécadatai, a csatolmányok | korlátlan |
| Forrásiratok | az eredeti helyükön maradnak; a rendszer nem másolja őket, csak tartalomhash-sel hivatkozik rájuk | a rendszer nem kezeli |
| Adattár-mentés | az adattár és a belső munkaanyag, helyben és a hálózati tárolón; titkosítás nélkül | mindkét helyen a legutóbbi 14 |
| Helyi kulcsfájl | a szolgáltatói kulcsok, titkosítás nélkül | korlátlan |
| Burr helyi nyomkövetője | csak egyes parancssori mérőparancsoknál: a folyamat lépései a felhasználói mappában; a feldolgozó nem használja | korlátlan |

A mentés nem teljes helyreállítás: a forrásiratok, a levelek, a futások mappája, a kulcsok és alapból a folyamatállapot-tár sincs benne. A visszaállítás kézi, leállított szolgáltatás mellett ([telepítési útmutató 6.](guides/SETUP.md)); helyreállítási gyakorlat még nem volt.

## 8. A GitHub és a kód

- **Privát tár.** A GitHubon csak a 2026-09-30-i második kiindulópont utáni történet van. A régebbi történet, amelyben személyes adat és belső munkaanyag is van, csak helyben, archív ágon él. Ezt és a régi címkéket a feltöltés előtti horog nem engedi feltölteni.
- **Adatőr** (2026-09-30 óta). Commit előtt és feltöltés előtt a gitbe kerülő új sorokat nézi. Megállít, ha valódi alakú értéket talál: olyan adószámot, IBAN-t vagy bankszámlaszámot, amelynek az ellenőrzőszáma helyes. A hibás ellenőrzőszámú érték biztosan kitalált, ezt átengedi. Megállít a nem kitalált e-mail-címre, a magyar telefonszámra, a külföldi adószámra, az ismert kulcs-alakokra, a helyi kulcsfájl bármely titkos értékére, és néhány tiltott kifejezésre (ezeket csak ujjlenyomattal tárolja). Útvonal alapján tiltja a belső munkaanyagot, a kulcsfájlt, a helyi adatmappákat, az irat-, kép- és adattárfájlokat és minden bináris fájlt. A kiírás mindig maszkolt.
- **Kivételek.** A kitalált mintaértékek egy verziózott kivétellistán vannak. Néhány régi saját érték tűrt ismert érték: csak ujjlenyomattal szerepel a listán, és csak abban a fájlban megy át, ahol most van. A legtöbbjük cseréje a 9. pont része (S-injekció, S-adatleltár).
- A horgokat klónonként egyszer kell bekapcsolni; az indítási ellenőrzés hibát jelez, ha nincsenek bekapcsolva. A megkerülésük tilos ([fejlesztési útmutató 1.](guides/DEVELOPMENT.md)).
- **Belső munkaanyag** (átadók, tervek, jelentések, teendőlista, döntésnapló) nincs a gitben. Helyben van, és a napi mentés viszi.
- **Külső csomagok.** A Python-csomagok listája rögzített. Az ismert sebezhetőséget kézzel ellenőrizzük (Python és felület), kiadás előtt és csomagfrissítés után; ez nem része az indítási ellenőrzésnek, és nincs ütemezve. A GitHub sebezhetőség-riasztása 2026-09-30 óta be van kapcsolva, automatikus javító kódmódosítás nélkül.
- **Melyik kód fut.** A szolgáltatás az egészség-válaszában és a Beállítások › Rendszer oldalon mutatja a kiadási verziót és az induláskori commitot, és jelzi, ha a futó kódban commitolatlan változás volt.

## 9. Nyitott tételek

- **S-injekció:** a „forrásszöveg adat, nem utasítás” védőmondat az irat-utasításokba, a rejtett-utasítás próba megismétlése, és a maradék saját adat cseréje; fizetős, a második-vélemény újraméréssel együtt.
- **S-adatleltár:** leltár arról, hol van személyes adat és meddig marad, ritkító paranccsal; döntés kell a megőrzési időkről.
- **S-titkosítás:** a hálózati tárolóra kerülő mentés titkosítása, és a gép lemez-titkosításának ellenőrzése.
- **S-helyreállítás:** próba, hogy a mentésből elkülönített helyen visszaáll-e a működő rendszer, leírt lépésekkel és mért idővel.
- **S-hitelesítés:** valódi belépés (jelszó vagy Windows-azonosítás) és jogosultság a névválasztás helyett; hálózati vagy többfelhasználós használat előtt kötelező.
- **Mappakorlát:** visszakapcsolása, mielőtt a szolgáltatást más is elérné.
- **S-függőségek:** a csomagok sebezhetőség-ellenőrzése rendszeresen fusson, dátummal látható eredménnyel.
- **Q-utolsó-író:** verzióellenőrzés a beállítások és a csomagadatok mentésénél, mert ma az utolsó mentés nyer; többfelhasználós használat előtt.

## 10. Hibabejelentés

A tár privát, egyetlen karbantartóval. Biztonsági hibát közvetlenül neki kell jelezni; nyilvános bejelentési folyamat nincs. A bejelentésbe ne kerüljön valódi irat, levél vagy kulcs: a hibát mesterséges példán kell megmutatni.

## Technikai részletek

**Helyi szolgáltatás** (`jav/api.py`, beállítás: `configs/service.json` 1.6.0):

| Védelem | Kód | Beállítás | Teszt |
|---|---|---|---|
| csak belső cím | `serve()`: a `host` a `LOOPBACK` halmazban, különben `ValueError` | `host`, `port` | `tests/test_api.py::test_serve_refuses_non_loopback_host` |
| gépnév (`Host`) | `_Guard`: `allowed_hosts` ∩ `LOOPBACK`, különben 403 `forbidden_host` | `allowed_hosts` | `tests/test_api.py::test_foreign_host_and_origin_are_refused` |
| eredet (`Origin`) | `_Guard`, `_origin()`: pontos séma + gép + port, különben 403 `forbidden_origin` | `dev_origins` | `tests/test_api.py::test_origin_must_match_the_service_or_the_dev_ui_exactly` |
| csak JSON, törzsméret | `_Guard`: `POST/PUT/PATCH/DELETE` csak `application/json` (415); a törzs korláttal előre beolvasva (413) | `max_body_bytes` = 262144 | `tests/test_api.py::test_body_must_be_json_and_bounded` |
| szerkezet | `_In` (`extra="forbid"`), `WpId`, `RunId`, `ItemId`, `Text` (2000 karakter) | – | `tests/test_api.py::test_schema_rejects_unknown_fields_and_bad_ids` |
| szerző | `human_actor`, `actor_unless_first_users`, `X-Actor` fejléc (URL-kódolva), `app_settings.ACTOR_RE`; ismeretlen név 403 `unknown_user` | Felhasználók lista | `tests/test_users.py`, `tests/test_api.py::test_actor_may_carry_accents_when_url_encoded` |
| forrásirat | `_item_file()`: a tétel `sha256`-a egyezik, különben 409 | – | `tests/test_api.py::test_item_source_is_served_only_for_unchanged_items` |
| mappakorlát | `checked_path()` (`resolve(strict=True)`), `allowed_roots()`, 403 `forbidden_path` | `restrict_paths` (false), `allowed_roots`, `allow_legacy_data_root`, `JAV_API_ROOTS` | `tests/test_api.py::test_folder_outside_allowed_roots_is_refused`, `::test_any_existing_folder_is_accepted_without_restriction` |
| végpontlista | `create_app()`: `docs_url=None`, `redoc_url=None`; `/api/openapi.json` marad | – | `tests/test_security_headers_071.py::test_interactive_docs_are_off_machine_list_stays` |
| védőfejlécek | `_SecurityHeaders` (legkülső réteg): `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy` és `Cross-Origin-Resource-Policy: same-origin`; CSP: `UI_CSP` (felület), `API_CSP` (`default-src 'none'`), `DOCUMENT_CSP` (PDF: csak `frame-ancestors 'none'`); `/api/` alatt `Cache-Control: no-store` | – | `tests/test_security_headers_071.py` |
| verzió | `jav/version.py` (`VERSION` a `pyproject.toml`-ból, `commit_info()`); `/api/health`: `version`, `commit`, `dirty`, `started_at` | – | `tests/test_version_071.py` |

**Bemenet, AI-hívások, jóváhagyás:**

| Védelem | Kód | Beállítás | Teszt |
|---|---|---|---|
| bemeneti korlát | `jav/pdf.py` (`check_document_size`, `DocumentTooLarge`, `InputLimits`, `fit_scale`), `jav/page_image.py`, `jav/ocr.py` (`PageTooLarge`) | `input_limits`: 100 MB, 300 oldal, 40 megapixel | `tests/test_input_limits_067.py` |
| rögzített bemenet | `jav/runtime/worker.py` (`source_changed`), `jav/work.py` készenlét | – | `tests/test_runtime_worker.py::test_changed_source_is_refused`, `tests/test_work.py::test_readiness_detects_changed_and_missing_source` |
| költségfoglalás, hívásnapló | `jav/runtime/calls.py` (`invoke`, `_reserve` egy `BEGIN IMMEDIATE` tranzakcióban, `BudgetExceeded`, `UncertainAttempt`) | `configs/recipes.json` `max_item_usd` | `tests/test_runtime_calls.py`, `tests/test_runtime_worker.py::test_budget_exhaustion_becomes_review_not_crash` |
| ár nélküli modell | `jav/config.py` `openai_price()`, `UnpricedModelError`; hívók: `jav/extract_llm.py`, `jav/email_tasks.py` | `configs/models.json` `openai.usd_per_mtok` | `tests/test_runtime_adapters.py::test_unpriced_model_is_refused_under_a_budget` |
| SDK-napló | `jav/config.py` `guard_sdk_logging()`: `TYPESAFE_LOG_LEVEL` `debug` vagy `info` értékénél a `typesafe_sdk` napló WARNING, kivéve `JAV_ALLOW_SDK_DEBUG=1` | környezeti változók | `tests/test_jev_adapter_v2.py::test_sdk_log_level_guard` |
| levél: beszúrt utasítás | `configs/callsites/email_intent.json` `prompt_injection` Noul; `jav/policy.py` `email_signal_reasons`, `email_signal_route` → `human:suspicious` | `configs/policy.json` `email.signal_review`, `email.signal_routes`, sáv: `email.signal` | `tests/test_email_signals.py::test_policy_signal_reasons_and_route` |
| feladatjavaslat-kapu | `jav/email_tasks.py` `gate()` (szó szerinti idézet), `skip_reason()` (`suspicious_signal`) | `configs/recipes.json` `tasks` (alap: `off`) | `tests/test_email_tasks.py` |
| jóváhagyási zár | `jav/work.py` `approve_run()` (`NotReady`) | – | `tests/test_api.py::test_approval_needs_apply_mode_and_no_open_reason`, `tests/test_work.py`, `tests/test_review_gate_066.py` |
| export-képletvédelem | `jav/export.py` `_safe_text()` (CSV: `'` elé), `_write_sheet()` (Excel: a szöveg `data_type="s"`); `jav/datasets.py` `export_file()` ugyanezt használja | `configs/reports.json` `export.formula_prefixes` | `tests/test_reports.py::test_csv_guards_formulas_but_keeps_numbers`, `tests/test_datasets.py::test_export_guards_formulas` |

**Levelek:**

| Védelem | Kód | Beállítás | Teszt |
|---|---|---|---|
| levélfogadó | `jav/ingest_server.py`: `_authorized()` (`Authorization: Bearer`, `hmac.compare_digest`), `_from_browser()`, `_read()` (`Content-Length` kötelező, `MAX_BODY_BYTES` = 2 MB), `validate_payload()`, `safe_mailbox_dir()`, `host_path()`; `make_server()` csak `127.0.0.1` | `JAV_INGEST_TOKEN` vagy `--token`, különben `secrets.token_urlsafe(24)` | `tests/test_ingest_security.py` |
| postafiók-letöltés | `jav/mailbox.py` `fetch()`: egyszeri kulcs, ideiglenes fogadó szabad porton; `MailboxRequest` (`_ACCOUNT`, `_FOLDER` minta, `extra="forbid"`) | – | `tests/test_mailbox.py` |

**GitHub és mentés:**

| Védelem | Kód | Beállítás | Teszt |
|---|---|---|---|
| adatőr | `jav/data_guard.py`, `scripts/githooks/pre-commit`, `scripts/githooks/pre-push`; bekapcsolás: `python -m jav.cli hooks-install` (`core.hooksPath`); teljes fa: `python -m jav.cli data-guard [--all]` | `configs/data_guard.json`: `forbidden_history`, `blocked_paths`, `blocked_extensions`, `allow`, `known`, `deny` | `tests/test_data_guard_071.py` |
| belső munkaanyag | `jav/doc_scope.py` (`INTERNAL_DOC_PATTERNS`), `.gitignore` | – | `tests/test_doc_scope_070.py`, `tests/test_doc_links.py` |
| mentés | `jav/backup.py` (`Connection.backup`, `PRAGMA integrity_check`, a másolat tartalomhash-sel ellenőrizve; `internal-docs.zip`) | `backup`: `keep` 14, `with_burr` false, `with_docs` true, `copy_to` | `tests/test_ops_064.py`, `tests/test_backup_docs_070.py` |

**Adathelyek** (7. pont): adattár `store/jav.sqlite`; folyamatállapot-tár `store/burr_state.sqlite`; mentés `store/backups/`; nyers futások `runs/`; JEV-gyorsítótár `runs/cache/`; OCR-gyorsítótár `runs/ocr/`; üzemi napló `runs/logs/` (`jav/runtime/applog.py`: `MAX_BYTES` 5 000 000, `BACKUPS` 5); levelek `inbox/`, csatolmányok `inbox/.bridge/data/`; kulcsok `.env`; a Burr nyomkövetője `~/.burr` (a könyvtár alapértelmezése; a feldolgozó `tracker=False`-szal fut).

**Mért próbák:**
- Iratok: `python -m jav.experiments.document_injection_probe --live`, `configs/experiments/document_injection.json` 1.0.0; modellek: `gpt-5.4-mini-2026-03-17`, `jev-1.13.0`; nyers futás: `runs/20260929_163752_067_injection/` (`rows.jsonl`, `summary.md`, `accounting.json`). Az S-út JEV-kérése a jelöltek ±1 sorára szűkül, ezért a cím alatti mondatot csak részben látja; a G-út a teljes szöveget kapja. Offline részek: `tests/test_document_injection_probe.py`.
- Levelek: `python -m jav.cli email-injection-probe` (`jav/evals_email.py` `INJECTIONS`: `clean`, `en_override_top`, `hu_override_top`, `hu_reroute_top`, `en_override_end`); nyers futás: `runs/20260920_153227_email_injection_probe.jsonl`; a hívási hely beállítása azóta változatlan (`configs/callsites/email_intent.json` 1.1.0).

**Kézi ellenőrzések** ([fejlesztési útmutató 6.](guides/DEVELOPMENT.md)): `uvx pip-audit -r requirements.lock --no-deps`; `cd ui; npm audit`. A GitHub sebezhetőség-riasztása a tár Dependabot-riasztása (bekapcsolva 2026-09-30); az automatikus javító kérés nincs bekapcsolva.
