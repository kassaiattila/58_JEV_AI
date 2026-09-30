# Fejlesztési munkamenet: git, ellenőrzés, átadás

**Érvényes:** 2026-09-27-től (040).

## Laikus összefoglaló

A projekt eddig verziókövetés nélkül futott. Ezért a lezárt mérések reprodukálhatóságát 223 fájl kézzel rögzített ujjlenyomata védte, és egy hibás változtatást nem lehetett egy lépésben visszavonni. Mostantól git rögzít minden változást. A fő ág mindig működő állapotban van, minden fejlesztési szakasz külön ágon készül, és minden mérés megnevezi a kódállapotot (commitot), amelyen futott.

## 1. Ágak és címkék

- A **`main`** mindig zöld: a `python -m jav.cli preflight` hibátlanul lefut rajta.
- A fejlesztés **szakaszonként külön ágon** folyik, a terv azonosítójával: `k1-adatmodell`, `k3-ui-munkacsomagok`. Kisebb javítás mehet `fix-<téma>` ágon.
- Az ág akkor kerül be a `main`-be, ha a teljes ellenőrzés zöld és az átadó elkészült. A beolvasztás `--no-ff`, hogy a szakasz egyben látsszon.
- **Címkék:** `baseline-039` a git bevezetése előtti állapot. Szakasz végén `k<N>-kesz` címke kerül fel. Lezárt méréshez `meres-<azonosító>` címke tehető, ha később reprodukálni kell.
- **Kiadási verzió (063):** a felhasználó által stabilnak jelölt állapot `vX.Y.Z` megjegyzéses címkét kap a `main` beolvasztó commitján, mellé kiadási jegyzet kerül (`docs/reports/ÉÉÉÉ-HH-NN-vX.Y.Z-kiadas.md`). Előtte kötelező a teljes `preflight` és egy élő végpróba tiszta munkafán. Javító kiadás (`vX.Y.Z+1`): hibajavítás; `feat` commit csak akkor kerülhet bele, ha egy javítást kiegészítő kis változás. Új képesség: `vX.Y+1.0`.
- **Távoli tároló (069, döntés 2026-09-29):** `origin` = `https://github.com/kassaiattila/58_JEV_AI.git` (privát).
  - A GitHubon a történet 2026-09-30 óta egy második kiinduló committal kezdődik (070, a felhasználó döntése): ez a `v1.0.4` utáni kódállapot, belső munkaanyag nélkül. Ez a `main` első commitja: `git rev-list --max-parents=0 main`.
  - A korábbi 236 commit és a címkék csak helyben vannak, az `archiv/elotortenet-069` ágon, mert a 066 előtti commitokban személyes adat van.
  - Az első, 069-es kiinduló commit (`669e851`) és a rá épülő commitok a belső munkaanyagot is hordozzák. Ezek az `archiv/elotortenet-070` ágon vannak.
  - A két archív ágat és a régi címkéket **soha ne töltsd fel**.
  - Feltöltés csak a `main`-re és az új kiindulópontból induló szakasz-ágakra, `git push origin <ág>`. A 070 előtti szakasz-ágak (például `k3-ui`, `v104-javitokor`, `d-dokumentacio-070`) a régi történetet hordozzák, ezért nem tölthetők fel. `--all`, `--tags`, `--mirror` tilos.
  - Új címke a feltöltés után csak az új kiindulópont utáni commitra kerülhet.
  - **Helyi védelem:** a `.git/hooks/pre-push` minden olyan ág vagy címke feltöltését elutasítja, amely a régi történetre épül (a `baseline-039` vagy a `669e851` az őse). A horog nincs verziókövetve (a verziózott változat a 070 S-adatőr tétele); egy friss klónban nincs rá szükség, mert abban nincs régi történet.
- **Belső munkaanyag (070, döntés 2026-09-29):** az átadókat, terveket, jelentéseket, a teendőlistát, a döntésnaplót, az útitervet és a helyi generált oldalakat a git nem követi. A kihagyási lista a `.gitignore`-ban van, egyetlen forrása a `jav/doc_scope.py`. Ezek a fájlok commitba és a GitHubra nem kerülnek, a napi mentés viszi őket. A régi állapotuk az archív ágakon olvasható. A `git add` csak kódtári fájlt vegyen fel; a `git add -f` belső útvonalra tilos.
  - **Csapda:** olyan commitra vagy ágra váltani, amely a belső fájlokat még követi (az archív ágak, a 070-es szétválasztás előtti commitok), a helyi belső fájlokat felülírja, a visszaváltás pedig törli őket. Ez 2026-09-30-án egy beolvasztásnál megtörtént; a fájlok egy aznapi commitból helyreálltak. Régi állapot megtekintése: `git show <commit>:<útvonal>`, vagy külön munkafa: `git worktree add ..\jav-regi archiv/elotortenet-070`. Előtte mentés: `python -m jav.cli backup --with-docs`.

## 2. Commit

```text
<típus>(<terület>): <rövid magyar összefoglaló>

<miért és mit, 1–5 sor; hivatkozás a tervre/BACKLOG-tételre>

Co-Authored-By: ...
```

Típusok: `feat` (új képesség), `fix` (hiba), `refactor` (viselkedés nem változik), `test`, `docs`, `chore` (eszköz, beállítás), `exp` (kísérlet, mérés). A terület a modul vagy a szakasz neve, például `runtime`, `mail`, `ui`, `k1`.

- Egy commit egy logikai változás. A hozzá tartozó teszt és kódtári dokumentáció ugyanabba a commitba kerül; a belső munkaanyag helyben frissül, commit nélkül.
- Commit előtt: `python -m jav.cli preflight --skip-pytest` és az érintett tesztek (`pytest tests/test_<x>.py`). Beolvasztás előtt: a teljes `preflight`.
- **Soha nem kerül a gitbe:** `.env`, `runs/`, `store/`, `inbox/`, OCR-nyelvcsomag, valódi irat vagy levél. Új teszthez **mesterséges vagy anonimizált** adat kell. Néhány régi teszt valódi számlákból vett cég- és személyneveket tartalmaz; ezek cseréje a K0 feladata, és távoli tárolóba feltöltés előtt kötelező.
- Távoli tároló (GitHub stb.) csak a felhasználó kifejezett döntése után jöhet.

## 3. Mérések és reprodukálhatóság

- Minden új mérés nyers futása és bizonylata rögzíti a **commit hash-t** és azt, hogy a munkafa tiszta volt-e. Nem tiszta munkafán élő, fizetős mérést nem indítunk.
- A 036-os befagyasztott fájllista (223 hash) a **régi** mérésekhez érvényes marad. Új mérésnél a commit és a címke helyettesíti.
- A kísérleti kód nem kerülhet a futtatókörnyezetbe importként. A kísérlet saját azonosítót, receptet és bizonylatot kap.

## 4. Session menete

1. **Indulás:** `python -m jav.cli preflight`, a legfrissebb átadó, `git status` és `git log --oneline -10` átnézése. Ezután rövid összefoglaló és egyeztetés a felhasználóval (CLAUDE.md 2. pont).
2. **Munka:** a szakasz ágán, kis commitokkal, TDD-vel, ahol kód változik.
3. **Lezárás:** a dokumentációs ellenőrzőlista ([DOCUMENTATION.md](DOCUMENTATION.md) 5. pont), zöld preflight, commit, majd átadó a commit hash-ével. Az átadó 2026-09-29 óta helyben marad, nem kerül commitba (070).

## 5. Mikor kell új átadó?

Csak a session végén és szakasz lezárásakor (a felhasználó döntése, 2026-09-27). Szakaszzárásnak számít egy lezárt mérés is, session-végnek az is, ha a kontextus nagyjából félig megtelt. A git-napló a finom szemcsés történet, ezért az átadó rövid lehet: mi készült, döntések, nyitott kérdés, következő lépés, csapdák. A futás végi hook 2026-09-27 óta nem kényszerít óránkénti átadót; csak emlékeztet a commitolatlan változásokra és az átadó óta készült commitok számára.

## 6. Biztonsági és minőségi ellenőrzések (067)

Ezek nem részei az indítási ellenőrzésnek. Kiadás előtt, függőség-frissítés után, vagy ha egy terület érzékeny változást kapott, érdemes futtatni őket. Egyik sem fizetős.

```powershell
uvx pip-audit -r requirements.lock --no-deps          # ismert sebezhetőség a rögzített Python-csomagokban (hálózat kell)
cd ui; npm audit; cd ..                               # ugyanez a felület csomagjaira
pytest tests/ --cov=jav --cov-report=term-missing     # tesztlefedettség: mely sorokat nem futtat teszt
$env:JAV_HYPOTHESIS_EXAMPLES = "3000"; pytest tests/test_properties_067.py   # a szabályalapú tesztek mélyebb kereséssel
```

A szabályalapú tesztek (`tests/test_properties_067.py`) nem egy-egy példát rögzítenek, hanem szabályt. Például: egy érvényes adószámot az ellenőrzés mindig elfogad, és egyetlen hibás számjegyét mindig észreveszi. Egy másik szabály: a végösszeg jelölt marad, bármilyen azonosító- vagy dátumsor kerül mellé. A `hypothesis` könyvtár kitalált bemenetek százait próbálja ki, és hiba esetén a legkisebb ellenpéldát mutatja. A tesztsorban tesztenként 150 próba fut. A bemeneti korlátok (fájlméret, oldalszám, oldalkép-képpont) a `configs/service.json` `input_limits` szakaszában vannak.
