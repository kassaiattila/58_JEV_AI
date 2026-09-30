# Felhasználói kézikönyv

**Érvényes:** 2026-09-30-tól (071, v1.0.5). **Kinek szól:** a felület felhasználójának.

## Laikus összefoglaló

A felület a böngészőben fut, és a saját gépen működő helyi szolgáltatáshoz kapcsolódik. Bejelentkezés nincs: minden változtatás a fejléc „Ki dolgozik?” mezőjében kiválasztott névhez kötődik. A munka egysége a munkacsomag, vagyis egy mappa iratai, megadott fájlok vagy egy postafiók levelei. A csomagon három lépésben dolgozol: a **Feldolgozás** szakaszban kiválasztod a receptet és elindítod a futást, az **Ellenőrzés** szakaszban az irat képe mellett rendezed a teendőket és javítod a hibás adatot, az **Eredmény** szakaszban letöltöd a táblákat és jóváhagyod az éles futást. Fizetős AI-hívást mindig ember indít, megerősítés után, előre látható költségkerettel.

## 1. Néhány fogalom előre

A teljes szótár a [fogalomtárban](../GLOSSARY.md) van. A kézikönyvhöz ennyi elég:

| Fogalom | Jelentés |
|---|---|
| Munkacsomag | Együtt kezelt iratok vagy levelek egy forrásból. Egy recept tartozik hozzá, és több futása lehet. |
| Recept | A feldolgozás leírása: milyen lépésekben, milyen beállításokkal és legfeljebb mekkora költséggel dolgozza fel a rendszer a csomag tételeit. |
| Futás | Egy recept elindítása a csomagon. Lehet **próba** (megtekinthető és letölthető, de nem adható ki) vagy **éles** (jóváhagyás után érvényes). |
| Teendő | Egy tételen emberi ellenőrzést kérő ok, például „Bizonytalan érték: Bruttó összeg (valószínűség 0,58)”. Okonként kell lezárni. |
| Feldolgozó | A háttérben futó program, amely a futások tételeit egyenként elvégzi. Ha nem fut, a futások várakoznak. |
| Helyi szolgáltatás | A program, amely a felületet kiszolgálja, és csak erről a gépről fogad kérést. |
| JEV és GPT | A két fizetős AI-szolgáltatás. A JEV zárt kérdésekre ad valószínűséget (melyik érték a helyes, igaz-e egy állítás), a GPT (az OpenAI szöveggeneráló modellje) szövegből olvas ki adatot. |

## 2. Indítás és a képernyő részei

1. A helyi szolgáltatást és a feldolgozót az indítószkript indítja el a háttérben (a pontos parancs a Technikai részletekben van). Elég egyszer elindítani: a böngésző vagy a lap bezárása nem állítja le, és a futó munkát sem szakítja meg.
2. Nyisd meg a böngészőben a http://127.0.0.1:8930/ címet. A cím csak ezen a gépen működik.
3. A bal oldali sávban két fő rész van: **Munkacsomagok** (a napi munka) és **Beállítások**.
4. A fejléc bal oldalán a feldolgozó jelvénye áll: „Feldolgozó fut” vagy „Feldolgozó nem fut”, és ha munka várakozik, „N tétel vár”. A piros „A helyi szolgáltatás nem érhető el” jelvény azt jelenti, hogy a szolgáltatás leállt (lásd a 11. pontot). Mellette a **HU / EN** nyelvváltó van.
5. A fejléc jobb oldalán a **„Ki dolgozik?”** mező áll.

### 2.1 „Ki dolgozik?”

- Minden módosító művelet a kiválasztott név alatt rögzül: csomag létrehozása és kezelése, recept, futás indítása és leállítása, javítás, teendő lezárása, jóváhagyás, feladatjavaslat-döntés, postafiók-letöltés, „Mentés most”. Így utólag is látszik, ki mit csinált. Név nélkül a szolgáltatás ezeket elutasítja („add meg a neved fent a „Ki dolgozik?” mezőben…”).
- Ha a Beállítások › Felhasználók lista nem üres, a mező választóként működik („Válaszd ki a neved”). Amíg nincs név kiválasztva, „Módosítás előtt válaszd ki a neved.” látszik. Csak a listán szereplő név fogadható el.
- Ha a lista üres, a név szabadon beírható. A „Mentés” gomb után „Megjegyezve” jelenik meg; a „Felhasználók felvétele” hivatkozás a névlistához visz.
- A név ebben a böngészőben megmarad, és minden nyitott lapra érvényes. Ha az egyik lapon átállítod, a többi lap is az új nevet mutatja.
- A név nem jogosultság és nincs mögötte jelszó: bárki bármelyik nevet kiválaszthatja.
- Kiválasztott névnél a mező mellett megjelenik a **„Mai munkám”** hivatkozás (9. pont).

### 2.2 Nyelv

A **HU / EN** gomb csak a feliratokat váltja. Az iratok adatai, a nevek és a fájlnevek nem változnak, a mentetlen javítás megmarad. A választás ebben a böngészőben megmarad. Ugyanez a Beállítások › Nyelv oldalon is beállítható.

## 3. A munkacsomagok listája

A **Munkacsomagok** oldal felül az **„Új munkacsomag”** gombbal indul, alatta a csomagok táblázata. Alapból a legújabb csomag áll elöl. Az oszlopok: „Név”, „Következő lépés”, „Utolsó futás”, „Tétel”, „Nyitott teendő”, „Forrás”, „Recept”, „Felelős”, „Utolsó tevékenység”, „Létrehozva”. A „Következő lépés” (például „Próbafutás indítása”, „Ellenőrzés: 3 teendő”, „Jóváhagyás”) a csomag megfelelő szakaszára visz. A „Nyitott teendő” a legutóbbi futás teendőit számolja, és az Ellenőrzésre visz. A lista magától frissül.

A táblázat minden listában ugyanígy működik:

- **Keresés:** a „Keresés az összes oszlopban…” mező nem különbözteti meg a kis- és nagybetűt, és az ékezetet sem („szamla” megtalálja a „Számla” szót).
- **Rendezés:** kattints az oszlopfejlécre (növekvő, csökkenő, kikapcsolva). Shift + kattintással további rendezési szint adható hozzá.
- **Szűrés:** az oszlopfejléc tölcsér jelén. Szövegnél „Tartalmazza”, számnál és dátumnál „Legalább” / „Legfeljebb”, felsorolt értéknél jelölőnégyzetek vannak, és mindenhol választható a „mind / csak üres / csak kitöltött”. Az aktív szűrők címkeként látszanak a táblázat fölött, és a × jellel egyenként, a „Minden szűrő törlése” gombbal együtt törölhetők.
- **„Csak a saját csomagjaim”:** csak azok a csomagok látszanak, amelyeknek te vagy a felelőse. Ehhez előbb nevet kell választani.
- **„Elrejtett csomagok is”:** az elrejtett csomagok is látszanak, egy „Csomag” oszloppal az állapotukról.
- **„Oszlopok (x/y)”:** itt kapcsolhatók be a rejtett oszlopok, például a „Nyitott teendő a korábbi futásokkal” vagy a „Forrás helye”. Az „Alaphelyzet” visszaállítja az eredeti oszlopokat. A választás táblánként megmarad ebben a böngészőben.
- **Lapozás:** alul „1–100 / N sor”, a laponkénti sorok száma (50, 100, 250, 500) és a lapozó gombok.

### 3.1 Letöltés

Minden táblázat jobb felső sarkában van **„Letöltés”** gomb. A panelen választható:

- **Formátum:** Excel (egy munkalap, a számok számként), CSV (pontosvesszővel tagolva, a magyar Excel oszlopokra bontja) vagy JSON (gépi feldolgozáshoz).
- **Sorok:** „Minden sor”, „A szűrt sorok” vagy „A kijelölt sorok”. Kijelölni csak a soronkénti jelölőnégyzettel rendelkező táblákban lehet (például az Eredmény tábláiban). Alapból a legszűkebb terjedelem van kiválasztva: kijelölés, ennek híján szűrés, végül minden sor.
- **Oszlopok:** csak a látható oszlopok, vagy minden oszlop a rejtettekkel együtt.

Letöltés előtt látszik a sorok és oszlopok száma, a sorrend a táblázatéval azonos. A fájl a böngésző letöltései közé kerül. A képletnek látszó szöveg a fájlban sem válik képletté.

## 4. Új munkacsomag

Az **„Új munkacsomag”** gomb három forrást kínál:

- **„Egy mappa PDF-jei”:** add meg a „Mappa teljes útvonala” mezőt. A csomagba a mappa közvetlen PDF-jei kerülnek, almappák nélkül, név szerinti sorrendben. A „Név” elhagyható, ilyenkor a mappa neve lesz.
- **„Megadott fájlok”:** a „Fájlok teljes útvonala, soronként egy” mezőbe több mappából is írhatsz fájlt. Itt a név kötelező.
- **„Postafiókból”:** a postafiók-űrlap (10.1 pont), a **„Letöltés most: új munkacsomag”** gombbal. A letöltést a feldolgozó végzi, az új levelekből a levél-recepttel rendelkező csomag lesz, amely a listában jelenik meg.

A „Létrehozás” után a csomag Feldolgozás szakasza nyílik meg, a létrehozó lesz a csomag felelőse. A fájlok a helyükön maradnak, a csomag csak hivatkozik rájuk. Meglévő csomagba a felületről nem lehet új iratot tenni: új iratokhoz új csomag kell (a munkamappa a saját csomagját magától is bővítheti).

## 5. A munkacsomag oldala

A fejlécben a csomag neve és egy összegzés áll (hány irat vagy levél, melyik recept, mikor volt az utolsó futás). Mellette:

- **„Felelős”:** a csomaghoz rendelt személy a Felhasználók listájából, vagy „nincs felelős”. Ez nem jogosultság, más is dolgozhat a csomagon; a „Csak a saját csomagjaim” szűrő ez alapján dolgozik.
- **A következő lépés gombja**, például „Próbafutás indítása →”. Ha éppen annak a szakasznak az oldalán vagy, csak a „Következő lépés: …” felirat látszik.
- **„Csomag kezelése”** (5.1 pont).

Alatta a három szakasz füle áll, mindegyik a saját állapotával: **1 Feldolgozás** (például „indítható”, „nincs recept”, vagy az utolsó futás módja, állapota és haladása), **2 Ellenőrzés** („N teendő” vagy „nincs teendő”), **3 Eredmény** („még nincs”, „próba-eredmény”, „jóváhagyásra vár”, „kiadva”). A csomag alapból annál a szakasznál nyílik meg, ahol a következő lépés van. A böngésző címsorában álló cím könyvjelzőzhető: ugyanarra a csomagra és szakaszra visz vissza.

A lehetséges következő lépések: „Üres csomag”, „Recept kiválasztása”, „Próbafutás indítása”, „Nem indítható”, „Fut: 3/10”, „Hibás vagy leállított futás: újrafuttatás”, „Ellenőrzés: N teendő”, „Próba rendben: éles futás”, „Jóváhagyás”, „Kiadva: eredmény letöltése”.

### 5.1 Csomag kezelése

- **„Átnevezés”:** új név megadása, majd „Mentés”.
- **„Elrejtés a listából”** / **„Visszahozás a listába”:** az elrejtett csomag futásai és eredményei megmaradnak, a csomag közvetlenül megnyitható, és az „Elrejtett csomagok is” jelölővel újra látszik a listában. A figyelt mappa elrejtett csomagba nem tesz új iratot, hanem új csomagot kezd.
- **„Végleges törlés…”:** csak olyan csomagon lehet, amelyen még nem volt futás. Megerősítést kér („Biztosan törlöd a csomagot?”). A csomag és a tétellistája törlődik, a fájlok a helyükön maradnak. A törlés nem vonható vissza, a ténye naplóban marad. Futással rendelkező csomag csak elrejthető.

## 6. Feldolgozás

### 6.1 A recept kiválasztása

A **„Recept”** kártyán választod ki, mit csináljon a rendszer a csomaggal. Három recept van:

| Recept | Mikor válaszd | Mit ad |
|---|---|---|
| „Számlák adatainak kinyerése” | Ha a csomagban egyféle, ismert típusú irat van (például csak magyar számlák). A típust te adod meg. | Iratonként mezőnkénti adat a forrásával, kódos ellenőrzéssel; ami bizonytalan, teendő lesz. |
| „Iratok felismerése és adatkinyerése” | Ha az iratok vegyesek vagy ismeretlen típusúak. | Iratonként a felismert típus, majd annak mezői. A nem eldönthető típus is teendő lesz. |
| „Levelek szándékának felismerése” | Postafiókból letöltött levelekhez. | Levelenként a felismert szándék (a levél célja, például számla érkezett) és a javasolt következő lépés; a PDF-csatolmányokból adat is; kérésre feladatjavaslat. |

A beállítások (a választott érték jelentése a kártyán mindig olvasható):

- **„Út”:** hogyan olvassa ki a rendszer az adatot. Az „automatikus” az irattípus ajánlott útját követi, a mindennapi munkához ez ajánlott. A „kód + JEV” (S-út) esetén a kód gyűjti ki a lehetséges értékeket, és a JEV választ közülük; olcsóbb, de tételsorokat nem olvas. A „GPT + JEV” (G-út) esetén a GPT olvassa ki az adatot a tételsorokkal együtt, a JEV mezőnként ellenőrzi; drágább.
- **„Irattípus”** (csak az első receptnél): melyik típus mezőit keresse a rendszer. A csomag minden iratán ugyanez fut.
- **„JEV-válaszok”:** a „korábbi válasz újrahasználható” esetén ugyanarra a kérdésre a korábbi válasz ingyen és azonnal jön, a mindennapi munkához ez ajánlott. A „mindig élő hívás” méréshez való, és a költség a keretig nőhet.
- **„Feladatjavaslat”** (csak a levél-receptnél): alapból „kikapcsolva”. Bekapcsolva a GPT levelenként javaslatot tesz, ami levelenként többletköltséggel jár.
- **„Költségkeret”:** tételenként és szolgáltatónként a legnagyobb összeg, amelyet a rendszer a futás indításakor lefoglal. Ez felső határ, a tényleges költség általában kisebb.

A kártyán sorban: „Recept” választó, leírás, „Mikor válaszd”, a lépések, a beállítások, „Megjegyzés (elhagyható)”, végül a **„Recept hozzárendelése”** gomb (meglévő receptnél „Módosítás”, majd **„Recept mentése”**). Minden mentés új változat, a korábbi futások a saját receptjüket őrzik. Ha közben más is módosította a receptet, az üzenet szól, a beállításaid megmaradnak, csak mentsd újra. Ha maga a recept változott a hozzárendelés óta, figyelmeztetés jelenik meg a **„Frissítés a recept mostani változatára”** gombbal. A receptek teljes leírása a Beállítások › Receptek oldalon van.

### 6.2 Készenlét

A **„Futtatás”** kártya indítás előtt megmutatja, mi akadályozza a futást. Ilyen akadály: „A munkacsomagban nincs tétel.”, „Nincs hozzárendelt recept.”, „A recept nem kezeli: …”, „Hiányzó forrás: …”, „A forrás tartalma a felvétel óta változott: …”. Akadály esetén az indító gombok tiltva vannak. Alattuk áll a csomag teljes költségkerete: „Költségkeret: JEV legfeljebb …, OpenAI legfeljebb …”.

### 6.3 Próbafutás, éles futás, újrafuttatás

- **„Próbafutás…”:** a feldolgozás teljesen lefut, ugyanazokkal a fizetős hívásokkal, de az eredmény csak megtekinthető és letölthető, nem adható ki. Új recept vagy új irattípus kipróbálására való.
- **„Éles futás…”:** az eredményt ember hagyja jóvá az Eredmény szakaszban, akkor, ha minden tétel lefutott és nincs nyitott teendő. Ez az érvényes eredmény.
- **„Újrafuttatás…”:** a legutóbbi futás megismétlése ugyanabban a módban, ugyanazzal a bemenettel, új futásként. Hiba, leállítás vagy a recept frissítése után hasznos.

A kiemelt gomb mindig az, amelyet a csomag következő lépése kér. Egy csomagon egyszerre egy futás mehet.

### 6.4 A megerősítő oldal

A három gomb nem indít azonnal, hanem egy összegző oldalra visz: „Munkacsomag”, „Tételek”, „Recept” a beállításaival és „Legnagyobb költség” szolgáltatónként, a „fizetős hívásokkal jár…” vagy „nem jár fizetős hívással” megjegyzéssel. A rendszer ilyenkor frissen lekéri a keretet („A költségkeret frissítése…”), addig az indítás tiltva van. Indítani a **„Próbafutás indítása”**, **„Éles futás indítása”** vagy **„Újrafuttatás indítása”** gombbal lehet, a „Mégse” visszavisz. Ha közben a csomag vagy a recept változott, ezt jelzi („…Frissítettük, nézd át és indítsd újra.”). Indítás után a futás oldala nyílik meg.

### 6.5 A futás oldala

- **Fejléc:** mód és időpont, állapot („Sorban áll”, „Fut”, „Teendő vár”, „Kész”, „Hibás”, „Leállítva”), a recept a beállításaival, és hogy ki indította.
- **„Tételek”:** tételenként a futás állapota, az eredmény és a teendők száma. A teendőre kattintva az Ellenőrzés nyílik meg.
- **„Költség”:** szolgáltatónként a lekötött összeg a kerethez képest. A lekötött összeg a lefutott hívások költsége, plusz a még le nem zárt hívások legrosszabb becslése.
- **„Munkasor”:** hány feladat áll sorban, fut, kész, hibás (feladva) vagy leállított.
- **„Hívásnapló (nyers modellhívások)”:** lenyitható lista a fizetős hívásokról. Üres, ha minden válasz a gyorsítótárból jött.
- **„Leállítás”** (csak futás közben): két kattintást kér („Biztosan? Kattints újra”). A sorban álló tételek azonnal, a futó tétel a következő lépése után áll le.
- **„Eredmény”** vagy éles futásnál **„Eredmény és jóváhagyás”**: a csomag Eredmény szakaszára visz.

A Feldolgozás szakaszban futás közben haladásjelző látszik, alatta „A csomag futásai” táblázat mutatja a csomag összes futását.

## 7. Ellenőrzés

Futás előtt az Ellenőrzés szakasz csak a csomag iratait mutatja (7.9 pont). Futás után itt a munkafelület nyílik meg.

### 7.1 A munkafelület

- **Felül:** a futásválasztó (alapból a legutóbbi futás, gépeléssel kereshető), a nyitott teendők száma, „A futás részletei” hivatkozás és a billentyű-súgó.
- **Balra a tétellista:** kereső („Keresés N tétel között…”) és „csak teendős” jelölő. Tételenként a név (levélnél a tárgy), az állapot („teendő”, „rendezve”, „lezárva”, „még nem futott”, „Hibás”…), valamint az „N teendő”, „N korábbi teendő” és „mentetlen” jel. A munkafelület az első teendős tétellel nyílik meg.
- **Középen** az irat oldalképe, **jobbra** a teendők és a mezők. A kettő közti elválasztó húzható (billentyűzettel a ← / → gombbal), az arány megmarad.

### 7.2 Teendők

- A jobb panel tetején a futás nyitott teendői állnak, okonként egy mondattal (például „Bizonytalan érték: Bruttó összeg (valószínűség 0,58)”, „Az adószám ellenőrző számjegye hibás”). Az ok szövegére kattintva a hozzá tartozó mező lesz kiválasztva.
- A **„Rendezve”** gomb azt az egy okot zárja le, a neveddel. A többi ok nyitva marad. **A mezőjavítás mentése a teendőt nem zárja le**, azt külön kell rendezni (kivétel a levél szándékának javítása, 7.8 pont).
- **„Korábbi teendők az iraton (N) — ezt a futást nem akadályozzák”:** egy régebbi futásból nyitva maradt okok. Rendezhetők, de ennek a futásnak a jóváhagyását nem akadályozzák.
- **Ellenőrzések a mentett adaton:** kódban írt szabályok (például hogy a tételek összege kiadja-e a végösszeget), amelyek a mentett javítás után fizetős hívás nélkül újra lefutnak. A hibás sorhoz „N. sor” gomb visz. A „csak jelzés, nem teendő” megjegyzésű ellenőrzés nem nyit teendőt.

### 7.3 Mezők, színek, keretek

- Mezőnként látszik a név, a „mentetlen” vagy „javítva” jel, a modell becslése százalékban, és egy forrásjel. A becslés színe a bizonyosság-sáv: zöld „Magabiztos”, kék „Ellenőrzendő”, piros „Valószínűleg hibás”. A „–” azt jelenti, hogy nincs becslés. A javított mező mindig kék, mert a becslés a gépi értékre vonatkozott. A szín csak megjelenítés, nem döntés, és nem bizonyítja, hogy az érték helyes.
- Forrásjel: ◉ a pontos hely megvan, ◎ csak közelítő hely van, ○ nincs hely. Ha az egeret a jel fölé viszed, magyarázat jelenik meg.
- Elöl a teendős mezők állnak, utánuk a „Valószínűleg hibás” mezők, végül a többi.
- A kiválasztott mező alatt látszik a „Forrásszöveg” az oldalszámmal, szükség esetén az, hogy az érték több helyen is szerepel, a javított mezőnél a „Gépi érték”, a „Más jelöltek” gombjai, és mentetlen módosításnál a „Visszaállítás”.
- **A képen** minden megtalált mező halvány keretet kap a sávja színével, a kiválasztott mező erőset. A kép a kiválasztott mező oldalára lapoz, és a keretet a látható részbe görgeti. A szaggatott keret közelítő hely (az a sor, ahonnan a gép választott), a lila keret kézzel kijelölt hely. A képre kattintva kiválasztódik a pont alatti mező, ismételt kattintással a következő átfedő mező. A képsávon lapozás („‹ ›”) és nagyítás („−”, százalék = alaphelyzet, „+”) van.
- Ha az iratnak nincs szórétege (egy korábbi futás vagy egy régi OCR-eredmény miatt), a mezők nem keretezhetők. Ezt a felület ki is írja; a keretekhez futtasd újra a receptet.

### 7.4 Javítás

Háromféleképpen javíthatsz:

1. **Beírás** a mező dobozába. Ha kitörlöd az értéket, az „nincs érték” javításként mentődik.
2. **Más jelölt választása:** a kiválasztott mező többi jelöltje szaggatott keretben, címkével („72%”, „gépi érték”, „lehetséges hely”) látszik a képen, és gombként a panelen is. Egy kattintással ez lesz a mező értéke, mentetlen javításként.
3. **„Kijelölés a képen”** (vagy az s billentyű): előbb válaszd ki a mezőt, aztán kattints a szavakra (ismételt kattintás kiveszi a szót), vagy húzz téglalapot. A rendszer a kijelölt szöveget a mező fajtája szerint értelmezi (dátum, összeg, adószám…), és megmutatja az eredményt („→ Mező: érték”). A **„Beírás a mezőbe”** gomb átviszi az értéket. Ha a szöveg nem értelmezhető, ezt jelzi („Ez a szöveg nem értelmezhető … értékként. Jelölj ki mást.”). A kijelölt hely a javítással együtt mentődik.

### 7.5 Tételes listák

Ha az iratnak van tételes listája (például számlatételek vagy kivonat-tranzakciók), a panel tetején fülek jelennek meg: „Mezők” és a lista neve a sorok számával; a „ •” jel mentetlen módosítást jelez. A lista cellái szerkeszthetők (a dátum alakja ÉÉÉÉ-HH-NN), a „Sor hozzáadása” gombbal új sor vehető fel, a × jellel sor törölhető, „A lista visszaállítása” pedig elveti a lista módosításait. A sorra kattintva a kép a sor helyére ugrik. Az ellenőrzésen elbukott sor piros. A javítás a teljes listára vonatkozik, a gépi lista változatlanul megmarad mellette.

### 7.6 Mentés és ütközés

- A **„Javítás mentése”** gomb (vagy Ctrl+Enter) új javításverziót ment, a gépi érték megmarad mellette. Alul „Javítás verziója: N” látszik. Mentéshez név kell.
- A mentetlen javítás (munkapéldány) megmarad, ha másik tételre lépsz, vagy ha a lapot újratöltöd. A lap bezárása előtt a böngésző figyelmeztet. Egy másik böngészőlap nem látja. A „Minden módosítás elvetése” gomb eldobja a munkapéldányt.
- **Ütközés:** ha közben valaki más is mentett ugyanarra a tételre, a mentés nem írja felül csendben az ő javítását. Ilyenkor „Közben más is mentett erre a tételre…” üzenet és piros doboz jelenik meg („A tételre közben újabb javítás került (verzió N). A munkapéldányod megmaradt.”). Az **„Alkalmazás az új verzióra”** a te módosításaidat az új verzióra teszi át; nézd át, majd mentsd újra. A **„Munkapéldány elvetése”** az új verziót hagyja meg.
- Jóváhagyott futáson a javítás le van zárva („A jóváhagyott futás javítása le van zárva.”).

### 7.7 Gyorsbillentyűk

A billentyűk kisbetűvel (Shift nélkül) és a beviteli dobozon kívül működnek. A Ctrl+Enter és az Esc a dobozban is él.

| Billentyű | Mit csinál |
|---|---|
| ↓ / ↑ (vagy j / k) | következő / előző mező |
| n / p | következő / előző tétel (a tételes lista fülén csak ez él) |
| s | kijelölés a képen be / ki (ha az iratnak van szórétege) |
| Enter | a kiválasztott mező dobozába lép |
| Esc | kilép a dobozból; kijelölésnél előbb a kijelölést törli, aztán a kijelölő módot kapcsolja ki |
| Ctrl+Enter | javítás mentése |

### 7.8 Levelek ellenőrzése

- **Balra a levél** áll: tárgy, „Feladó”, „Címzett”, „Érkezett”, „Csatolmány” és a szöveg. A linkek nem kattinthatók, helyettük „link: gépnév” látszik, a teljes cím az egér alatt olvasható. Jelzés figyelmeztet, ha a szándék-felismerés csak a levél elejét látta, vagy ha a szöveg már a letöltéskor elvágódhatott.
- **Jobbra** a teendők állnak „Rendezve” gombbal, a **„Felismert szándék”** a modell becslésével, vagy a „Kézzel javítva (a gép szerint: …)” / „Kézzel megerősítve” jelzéssel.
- **„Szándék javítása”:** válaszd ki a helyes szándékot. Ha a mostani szándékkal egyezik, a gomb „Megerősítés”, különben „Javítás mentése”. Mentéskor a levél bizonytalan szándék miatti teendője lezárul, és a **„Javasolt következő lépés”** (például „Kézi feldolgozás”, „Archiválás”, „Adatkinyerés a csatolmányból (…)”) a javított szándékból számolódik újra.
- **„Feladatjavaslatok (elfogadni csak ember tud)”:** csak akkor, ha a receptben a feladatjavaslat be van kapcsolva. Javaslatonként látszik a cím, az akció, a „Határidő” és a „Felelős” (csak ha a levélben szó szerint szerepel), valamint a „Bizonyíték” idézetei. Gombok: **„Elfogadás”**, **„Elvetés”**, az elfogadott javaslaton **„Elvégezve”** (a neveddel és az időponttal) és **„Elvégzés visszavonása”**. Az azonos javaslatok össze vannak vonva („N azonos javaslat összevonva”). A bizonyíték-ellenőrzésen kiesett javaslatok lenyitható listában látszanak, azzal együtt, hogy melyik részük nem igazolható. Archiválandó levélen (hírlevél, értesítés) nem kérünk javaslatot. Ha egy levél minden javaslatáról döntöttél, a javaslatokhoz tartozó teendő magától lezárul (ennek a teendőnek jelenleg nincs magyar felirata, rövid gépi kóddal látszik).
- **„Csatolmányok felismerése”** és **„A csatolmányok adatai”:** a PDF-csatolmány a csomagban külön iratként fut. A „…: az adatkinyerés eredménye →” hivatkozás a csatolmány ellenőrző nézetére visz.

### 7.9 Iratok kezelése

Futás után a munkafelület alatt lenyitható az **„Iratok kezelése: megnyitás, letöltés, eltávolítás”** rész, futás előtt ez az Ellenőrzés egyetlen tartalma. Soronként: **„Megnyitás”** (új lapon), **„Letöltés”**, **„Eltávolítás”**. Az eltávolítás megerősítés nélkül kiveszi a tételt a csomag listájából, a fájl a helyén marad, a korábbi futások bemenete nem változik.

## 8. Eredmény

- Alapból a legutóbbi futás eredménye látszik. Ha a csomagnak több futása van, futásválasztó jelenik meg.
- A nézetek (csak azok, amelyekhez van adat): **„Levelek”**, **„Feladatok”**, **„Iratok”**, **„Adatpontok”**, **„Tételsorok”**, **„Közmű-költség”**. Levélcsomagnál a Levelek, egyébként az Adatpontok nyílik meg.
  - „Iratok”: iratonként egy sor (típus, út, állapot, nyitott teendők, levél-csatolmánynál a forrás-levél tárgya) és mezőnként egy oszlop.
  - „Adatpontok”: mezőnként egy sor (érték, oldal, forrásszöveg, hely, javítva-e, teendő a mezőn).
  - „Tételsorok”: a tételes listák sorai.
  - Mindenhol az érvényes adat látszik, vagyis a gépi érték az emberi javítással. Az irat nevére kattintva az Ellenőrzés nyílik meg.
- A táblák sorai jelölőnégyzettel kijelölhetők, és a kijelölt sorok külön is letölthetők (3.1 pont). A **„Teljes Excel-csomag”** gomb a futás összes tábláját (a közmű-költséggel együtt) egy többlapos Excel-fájlba teszi.
- **„Közmű-költség”:** a közmű-számlák bruttó összege fogyasztási hely és közmű szerint, havonta. A többhónapos számla a napok arányában oszlik meg. A cellában az összeg, vagy „hiányzik” (egyik számla sem fedi a hónapot), „részleges” (a hónap egy része fedetlen), „átfedés” (két számla is fedi) áll. A * jel elszámoló számlát jelöl. A tájékoztató sorok nem számítanak bele az összesenbe. Egy cellára kattintva megjelennek a forrásszámlái, „megnyitás” hivatkozással. Az ismétlődő számlát a riport egyszer számolja, és ezt ki is írja.
- **Jóváhagyás:**
  - Próbafutásnál a felület kiírja, hogy az eredmény nem adható ki; ehhez éles futás kell.
  - Éles futásnál a **„Jóváhagyás és kiadás”** gomb csak akkor aktív, ha a futás lezárult, és nincs nyitott teendő; addig a felület kiírja, hány teendő van még. A gomb két kattintást kér.
  - Jóváhagyás után „Kiadva: jóváhagyta …, …” látszik. A futás mezőjavításai, szándék-javításai és feladatjavaslat-döntései ezzel lezárulnak; az elfogadott feladat „elvégezve” jelölése továbbra is lehetséges. A jóváhagyás a felületről nem vonható vissza. A letöltés utána is elérhető.

## 9. Mai munkám

A fejléc **„Mai munkám”** hivatkozása a kiválasztott személy napi műveleteit mutatja: recept, futás indítása és jóváhagyása, javítás, teendő lezárása, feladatjavaslat-döntés, csomag-módosítás, postafiók-letöltés. A „Nap” mezőben korábbi nap is választható. A táblázat oszlopai: „Időpont”, „Művelet”, „Munkacsomag”, „Részlet”, „Futás”.

## 10. Beállítások

A Beállítások bal oldali menüjében hét pont van.

### 10.1 Postafiókok

A postafiók-letöltés a gépen futó Outlookból hozza be a leveleket.

- **Mit olvassunk:** „Postafiók címe” (több is, vesszővel, pontosan úgy, ahogy az Outlookban szerepel; a „Korábban használt” címek egy kattintással hozzáadhatók vagy kivehetők), „Mappa” (vesszővel), „almappákkal”, az időszak („Az utolsó napok” a „Napok száma” mezővel, vagy „Dátumtól dátumig”), és „Legfeljebb ennyi levél (0 = nincs korlát)”.
- **„Hány levél? (ingyenes)”:** előnézet arról, hány levél esik az időszakba, ebből mennyi új, és mennyi volt már beolvasva (ezeket kihagyja).
- **Ütemezés** (csak „az utolsó napok” időszakkal): gyakoriság (15 percenként, félóránként, óránként, 4 óránként, naponta), majd „Ütemezés mentése”. Az **„Ütemezések”** táblában a gyakoriság módosítható, az ütemezés ki- és bekapcsolható vagy törölhető. Az ütemezés csak akkor fut, ha a feldolgozó fut, és az Outlook nyitva van.
- **„Letöltések”:** minden letöltés állapota, az új levelek száma, a létrejött munkacsomag és az esetleges hiba.
- A letöltést a feldolgozó végzi, közben az iratok feldolgozása vár. Az új levelekből munkacsomag lesz, de fizetős futás nem indul magától.

### 10.2 Munkamappák

A munkamappa (figyelt mappa) olyan mappa, amelyet a feldolgozó a megadott gyakorisággal átnéz, és az új PDF-ekből munkacsomagot készít, vagy a meglévőt bővíti. Mappánként megadható: „Név”, „Mappa teljes útvonala”, „Aktív”, „Almappák is”, a csomagolás („Egy közös csomag” vagy „Napi csomagok”), a „Recept” (vagy „Nincs (a csomagon kell kiválasztani)”) és az „Átnézés” gyakorisága. A **„Munkamappa hozzáadása”**, az „Eltávolítás”, a „Módosítások elvetése” és a **„Mentés”** gomb kezeli a listát. Mentetlen módosításnál az oldal elhagyása megerősítést kér. Mentett mappán az **„Átnézés most”** azonnal átnéz; a még íródó fájl a következő átnézésre marad. A forrásmappához a rendszer csak olvasásra nyúl, és fizetős futás nem indul magától.

### 10.3 Receptek

Minden recept teljes leírása: mire való, mikor válaszd, mi kell hozzá, a lépések, az eredmény, az ember teendője, a költségkeret alapbeállítással, és minden beállítás minden lehetséges értéke a jelentésével. Itt nem lehet módosítani, ez csak olvasható leírás.

### 10.4 Felhasználók

A „Ki dolgozik?” választéka. Az „Új név” mezővel és a „Felvétel” gombbal vehetsz fel új nevet, a „Törlés” gombbal törölhetsz. Mindkettő azonnal mentődik. A név betűt, számot, szóközt, pontot, @ jelet és kötőjelet tartalmazhat, legfeljebb 64 karakter hosszan. Ha a lista nem üres, módosítani csak a listán szereplő névvel lehet, és a csomag felelőse is innen választható.

### 10.5 Megjelenés

„Téma”: „A rendszer szerint”, „Világos” vagy „Sötét”. „Sűrűség”: „Tágas” vagy „Tömör”. Azonnal érvényes, és ebben a böngészőben megmarad.

### 10.6 Nyelv

„Magyar” vagy „English”, ugyanaz, mint a fejléc HU / EN gombja (2.2 pont).

### 10.7 Rendszer

- **„Verzió”:** a futó kiadási verzió és a commit (a kód egy rögzített, azonosítóval ellátott állapota a verziókezelőben), valamint az, hogy mióta fut a szolgáltatás. Új kód csak a szolgáltatás újraindítása után lép életbe. „A futó kód commitolatlan változást tartalmaz.”: a futó kódban olyan módosítás is van, amely még nincs rögzítve, tehát nem pontosan egy kiadott állapot fut. „A commit nem ismert…”: a szolgáltatás verziókezelő nélkül indult.
- **„Feldolgozó”:** „Fut” vagy „Nem fut”, és a munkasor számai (sorban, folyamatban, kész, leállítva, feladva). A **„Leállítás”** két kattintást kér, és a feldolgozó a folyamatban lévő tétel után áll le. Újraindítani csak az indítószkripttel lehet.
- **„Adattár-mentés”:** az adattár (csomagok, futások, javítások, döntések) ellenőrzött másolata. Naponta a beállított időpontban magától lefut, és egy másolat egy második helyre (például hálózati tárolóra) is kerül. A panel állapota „Rendben”, „Figyelem” vagy „Hiba”, alatta a helyi mentés és a másolat helye. A „Belső dokumentumok” sor a fejlesztés helyi jegyzeteinek mentését mutatja, a napi munkához nincs köze. A **„Mentés most”** azonnal ment. Ha a legutóbbi sikeres mentés régebbi a beállított óraszámnál (alapból 36 óra), figyelmeztetés jelenik meg.
- **„Minden futás”:** az összes csomag összes futása egy táblában.

## 11. Hibaelhárítás

| Mit látsz | Mit jelent | Mit tegyél |
|---|---|---|
| A böngésző nem tudja megnyitni a címet, vagy a fejlécben piros „A helyi szolgáltatás nem érhető el” áll; műveletnél „A helyi szolgáltatás nem érhető el. Fut a …?” | A helyi szolgáltatás nem fut. | Indítsd el az indítószkripttel. Ha újra leáll, az üzemi napló utolsó sorai mutatják az okát (Technikai részletek). |
| „Feldolgozó nem fut”, a futások „Sorban áll” állapotban maradnak, a postafiók és a munkamappa nem frissül | A feldolgozó leállt, vagy leállították. | Futtasd újra az indítószkriptet: csak a hiányzó részt indítja el. |
| Mentéskor „Közben más is mentett erre a tételre…”, vagy piros doboz: „A tételre közben újabb javítás került (verzió N)” | Valaki más közben új javítást mentett ugyanarra a tételre. | „Alkalmazás az új verzióra”, átnézés, újra mentés; vagy „Munkapéldány elvetése”. A munkád nem veszett el. |
| Receptnél, indításnál vagy eltávolításnál „…közben változott. Frissítettük…” | A csomag vagy a recept közben módosult. | Nézd át a frissített állapotot, és ismételd meg a műveletet. |
| „add meg a neved fent a „Ki dolgozik?” mezőben…” vagy „…válaszd ki a neved a Felhasználók listájából” | Nincs kiválasztott név, vagy a név nincs a listán. | Válassz nevet a fejlécben; ha hiányzik, vedd fel a Beállítások › Felhasználók oldalon. |
| Postafiók-előnézetnél „Az Outlook nem fut ezen a gépen. Indítsd el, és próbáld újra.”; a „Letöltések” táblában a hiba angolul is megjelenhet („Outlook must already be running…”) | A letöltés a gépen futó Outlookból olvas. | Indítsd el az Outlookot, és próbáld újra. |
| „Ez a cím egyetlen Outlook-fiókkal sem egyezik ezen a gépen.” | A megadott cím nem egyezik egyetlen Outlook-fiókkal sem. | Írd be a címet pontosan úgy, ahogy az Outlookban szerepel. |
| „A régi Outlook-szkript nem található a régi projektben; a letöltés nem működik.” | Hiányzik a letöltést végző régi szkript. | Szólj a gép gazdájának; a telepítést a [telepítési útmutató](SETUP.md) írja le. |
| „A legutóbbi sikeres mentés N órája készült; a napi mentés valószínűleg nem fut.” | A napi automatikus mentés nem futott le. | „Mentés most”, és szólj a gép gazdájának, hogy ellenőrizze az ütemezett feladatot. |
| „A helyi mentés rendben…, de a másolat a második helyre nem sikerült: …” | A második hely (például a hálózati tároló) nem volt elérhető. | Ellenőrizd a hálózati kapcsolatot, majd „Mentés most”. |
| Teendő: „A JEV nem volt elérhető (…); ellenőrizd kézzel”, levélnél „Kézi ellenőrzés: a JEV nem volt elérhető” | A JEV nem válaszolt, vagy a tétel költségkerete elfogyott. A futás ettől nem állt le, csak ezt a tételt küldte kézi ellenőrzésre. A zárójelben rövid angol ok áll (Technikai részletek). | Ellenőrizd a mezőket a képen, javítsd, és „Rendezve”; vagy később „Újrafuttatás…” (ez új fizetős hívásokkal jár). |
| Akadály: „Hiányzó forrás: …” vagy „A forrás tartalma a felvétel óta változott: …” | A fájlt a felvétel óta áthelyezték, törölték vagy módosították. | Tedd vissza az eredeti fájlt; vagy vedd ki a csomagból (7.9 pont), és a módosított fájlból készíts új csomagot. |
| „Ehhez az irathoz nincs szóréteg…” | Az iratnak ebből a futásából hiányzik a szavak helye. | Futtasd újra a receptet. |
| „Ez a mappa nincs az engedélyezett helyek között…” | A mappakorlát be van kapcsolva a szolgáltatás beállításában (alapból ki van kapcsolva). | Válassz engedélyezett mappát, vagy kérd a korlát módosítását (Technikai részletek). |
| „Váratlan hiba a felületen” | Egy nézet hibára futott. | „Újratöltés”. A mentetlen javítások megmaradnak. |

## 12. Mit nem csinál a felület

- Nincs bejelentkezés és jelszó. A „Ki dolgozik?” név csak a szerzőt rögzíti, nem jogosultság.
- Csak erről a gépről érhető el, más gépről vagy idegen weboldalról érkező kérést a szolgáltatás elutasít.
- Fizetős futást nem indít magától, a munkamappa és a postafiók-ütemezés sem.
- A forrásfájlokat nem módosítja és nem törli. A csomag törlése és a tétel eltávolítása csak a listából veszi ki őket.
- A levelekben lévő linkeket nem nyitja meg.
- A modell becslése és két modell egyetértése nem bizonyítja, hogy az érték helyes: a felület ezért kér emberi ellenőrzést.
- A mentésből való visszaállítás, a bizonytalan kimenetű fizetős hívás rendezése és a feldolgozó újraindítása nem a felületen történik (Technikai részletek).

## Technikai részletek

**Indítás és leállítás** (a projekt gyökeréből, PowerShellben; telepítés: [SETUP](SETUP.md)):

```powershell
.\scripts\dev.ps1 start    # helyi szolgáltatás (127.0.0.1:8930) + egy feldolgozó a háttérben; a már futó részt nem indítja újra
.\scripts\dev.ps1 status   # fut-e a szolgáltatás és a feldolgozó, mennyi feladat vár
.\scripts\dev.ps1 stop     # a feldolgozó a folyamatban lévő tétel után lép ki, a szolgáltatás azonnal leáll
```

- **Cím:** `http://127.0.0.1:8930/`. A felület a `/api/...` végpontokat hívja. A `/api/health` adja a Verzió kártya adatait (verzió, commit, commitolatlan változás, indulás ideje). A kattintható végpontlista (`/api/docs`) ki van kapcsolva. A biztonsági beállításokat a [biztonsági leírás](../SECURITY.md) tartalmazza.
- **Üzemi napló:** `runs\logs\api.log` és `runs\logs\worker.log`; az indítószkript kimenete: `runs\dev\*.log`.
- **Parancssori párok:** `python -m jav.cli worker-status`, `worker-stop`, `backup`; bizonytalan kimenetű fizetős hívás: `calls-uncertain`, `calls-resolve <id> [--cost USD] --note N`. A mentésből való visszaállítás kézi, leállított szolgáltatás mellett: [SETUP 6.](SETUP.md). A napi mentést a Windows Feladatütemező indítja (`scripts\backup-task.ps1`).
- **A JEV-teendő zárójeles oka:** `budget_exceeded` (a tétel költségkerete elfogyott), `uncertain_attempt` (egy korábbi fizetős kísérlet kimenete ismeretlen, kézzel kell rendezni), egyéb érték: a szolgáltatás hibája vagy időtúllépése.
- **Beállításfájlok** (részletek: [beállításfájlok útmutatója](CONFIGS.md)):
  - receptek: `configs/recipes.json`; a magyarázó szövegeik: `configs/recipe_help.json`;
  - bizonyosság-sávok (`confidence_bands`, alapból 0,9 és 0,5), mentés (`backup`: időpont, megtartott darabszám, `max_age_hours`), mappakorlát (`restrict_paths`, `JAV_API_ROOTS`): `configs/service.json`;
  - mezők és irattípusok magyar neve: `configs/field_labels.json`; levél-szándékok: `configs/intents.json`; feladatjavaslat-akciók: `configs/email_tasks.json`.
- **A böngészőben tárolt adatok** (nézőnként, nem kerülnek az adattárba): név `jav.actor`, nyelv `jav.ui-language`, megjelenés `jav.appearance`, oszlopláthatóság `jav.table.<tábla>.cols`, a kép és a panel aránya `jav.review.split` (a tételes lista fülén `jav.review.split.list`); a munkapéldány laponként: `jav.drafts` (sessionStorage).
- **Forráskód:** a felület `ui/src/` (nézetek: `views/`, ellenőrzés: `review/`, feliratok: `labels.ts`, angol fordítás: `i18n/en-*.json`); a szolgáltatás `jav/api.py`, a táblák oszlopai `jav/datasets.py`, a következő lépés `jav/work_views.py`. Felépítés: [ARCHITECTURE 8.](../ARCHITECTURE.md#8-munkafelület-040-k3-2026-09-27).
- **Fő feliratok angolul** (EN nézet):

| Magyar | English |
|---|---|
| Munkacsomagok · Beállítások | Work packages · Settings |
| Ki dolgozik? · Mai munkám | Who is working? · My work today |
| Új munkacsomag · Csomag kezelése | New work package · Manage package |
| Feldolgozás · Ellenőrzés · Eredmény | Processing · Review · Result |
| Próbafutás · Éles futás · Újrafuttatás | Trial run · Live run · Rerun |
| Rendezve · Javítás mentése · Kijelölés a képen | Resolved · Save correction · Select on image |
| Jóváhagyás és kiadás · Mentés most | Approve and release · Back up now |
