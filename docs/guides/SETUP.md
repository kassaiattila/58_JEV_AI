# Telepítés és helyi környezet

**Érvényes:** 2026-09-27-től (040). **Platform:** Windows 11, PowerShell 5.1, Python 3.12.

## Laikus összefoglaló

Ez az útmutató leírja, mi kell ahhoz, hogy a projekt egy gépen elinduljon. A gitben csak a forráskód, a beállítások és a dokumentáció van. A kulcsok, a helyi adatok és a nagy OCR-nyelvcsomagok nincsenek benne, ezeket gépenként kell beszerezni.

## 1. Python-környezet

```powershell
uv venv --python 3.12 .venv
uv pip install -r requirements.lock
.\.venv\Scripts\Activate.ps1
python -m jav.cli hooks-install      # adatőr: commit és feltöltés előtti ellenőrzés (071), klónonként egyszer
python -m jav.cli preflight          # teszt + kontraktus + konfig + adatőr + állapot
```

**Adatőr (071).** A `hooks-install` a gitet a verziózott horgokra állítja (`scripts/githooks/`). Ezután minden commit és feltöltés előtt lefut egy ellenőrzés, amely megállítja a műveletet, ha a gitbe kerülő sorokban személyes adat vagy kulcs van. Ilyen például egy valódi alakú adószám, bankszámlaszám, e-mail-cím, telefonszám vagy a `.env` egy kulcsa. Megállítja akkor is, ha belső munkaanyag, irat, kép vagy adattár kerülne a gitbe. Amíg a horgok nincsenek bekapcsolva, az indítási ellenőrzés hibát jelez. A szabályok: [DEVELOPMENT §1](DEVELOPMENT.md).

**Felület (040 K3).** Node.js 20.19 vagy újabb kell hozzá:

```powershell
cd ui; npm ci; npm run build; cd ..   # függőségek a package-lock.json szerint, build a ui/dist-be
.\scripts\dev.ps1 start             # szolgáltatás + feldolgozó; a felület: http://127.0.0.1:8930/
```

**Saját mappák a felületen (046, 061).** A felhasználó 2026-09-28-i döntése óta bármely létező helyi mappa vagy fájl megadható a felületen (munkacsomag, munkamappa). A korlát a `configs/service.json` `restrict_paths: true` beállításával visszakapcsolható. Ekkor iratot csak engedélyezett mappából lehet felvenni: a projekt `inbox/` és `data/` mappája, a régi projekt adatai, valamint a `.env`-ben a `JAV_API_ROOTS` változóban felsorolt mappák (több mappa `;`-vel elválasztva, idézőjelben, ha szóköz van benne). Példa: `JAV_API_ROOTS="D:\Számlák\Bejövő"`. A módosítás után `.\scripts\dev.ps1 stop` és `start` kell. A valódi iratok mappája a gépen marad, a gitbe nem kerül.

Fejlesztés közben az `npm run dev` a `http://127.0.0.1:5173/` címen fut, és a kéréseket a szolgáltatáshoz továbbítja.

## 2. Kulcsok

Másold a `.env.example`-t `.env` néven, és töltsd ki: `TypeSafeJAV_API_KEY`, `OPENAI_API_KEY`. A `.env` soha nem kerül a gitbe. Kulcsértéket ne írj ki naplóba vagy dokumentumba.

## 3. OCR (szöveg nélküli PDF-ekhez)

- **Tesseract 5.x** natívan: `%LOCALAPPDATA%\Programs\Tesseract-OCR`. Nem kell a PATH-on lennie, a helyét a `configs/ocr.json` adja meg.
- **Nyelvcsomagok** (a gitben nincsenek, git-ignorálva): `tools/tessdata/` (eng, hun, osd; ezt használja a projekt) és `tools/tessdata_best/`. Beszerzés: a tesseract-ocr `tessdata_fast` és `tessdata_best` kiadásából, vagy a régi sidecar Docker-képéből, ahonnan az eredeti példány jött. A `python -m jav.cli ocr` parancs PDF nélkül kiírja a motor és a nyelvcsomagok állapotát.
- A fizetős Azure Document Intelligence eszkaláció a régi projekt sidecar-konténerén át megy. Csak akkor kell, ha a gyenge helyi OCR-t eszkalálni akarjuk.

## 4. Függés a régi projekttől

A `jav/config.py` rögzített útvonalon hivatkozza a `C:\00_DEV_LOCAL\10_AIFLOW_V4` projektet: a golden etalonokat, a régi adatkönyvtárat és az Outlook-bridge-et. Ezek csak olvasásra kellenek a méréshez és a levélfogadáshoz. A napi tesztekhez nem kellenek. A hely a `JAV_LEGACY_ROOT` környezeti változóval (vagy `.env`-sorral) felülírható; alapértéke a fenti útvonal.

## 5. Helyi, git-ignorált könyvtárak

| Könyvtár | Tartalom | Törölhető? |
|---|---|---|
| `runs/` | nyers futások, bizonylatok, modell- és OCR-gyorsítótár | Nem: a lezárt mérések bizonyítéka |
| `store/` | helyi SQLite-adattár (PII) | Nem |
| `inbox/` | beérkezett levelek (PII) | Nem |
| `docs/handoffs/`, `docs/plans/`, `docs/reports/`, a teendőlista, a döntésnapló és a többi belső munkaanyag (lista: `jav/doc_scope.py`) | a fejlesztés menetének helyi dokumentumai (070); friss klónban nincsenek meg | Nem: nincs verziókövetésük, csak a napi mentésben van másodpéldányuk |
| `tools/tessdata*/` | OCR-nyelvcsomagok | Igen, újra beszerezhető |
| `.venv/` | Python-környezet | Igen, a lockfile-ból újraépíthető |

## 6. Mentés, visszaállítás és napló (063)

**Laikus összefoglaló:** az adattár (a munkacsomagok, futások, javítások és döntések) egy parancsra menthető, a szolgáltatás futása közben is. A mentés az adattár sértetlenségét is ellenőrzi. 2026-09-29 óta naponta 12:00-kor magától is lefut, és egy ellenőrzött másolat a hálózati tárolóra (NAS) is kerül; mindkét helyen a legutóbbi 14 mentés marad. 2026-09-30 óta a napi mentés a belső munkaanyagot (átadók, tervek, jelentések, teendőlista, döntésnapló) is viszi, mert ezeket a git nem követi. A legutóbbi mentés állapota a Beállítások › Rendszer oldalon látszik. A szolgáltatás és a feldolgozó hibái állandó naplófájlba kerülnek, így egy leállás oka utólag is kideríthető.

**Mentés:**

```powershell
python -m jav.cli backup                 # store\backups\<időbélyeg>\jav.sqlite + manifest.json; a legutóbbi 14 marad (a napi mentés megőrzése, 066)
python -m jav.cli backup --with-burr     # a folyamat-állapotok tára is (store\burr_state.sqlite, nagy: több száz MB)
python -m jav.cli backup --with-docs     # 070: a belső munkaanyag is (internal-docs.zip; a napi mentés ezt alapból teszi)
python -m jav.cli backup --out D:\Mentes --keep 30
```

A parancs az SQLite saját mentő eljárását használja (a futó adattárról a sima fájlmásolás hibás lehet), és a másolaton lefuttatja a sértetlenség-ellenőrzést. A mentés személyes adatot tartalmaz, ugyanúgy kell kezelni, mint a `store\` mappát.

**Napi mentés (064):** a beállítás a `configs\service.json` `backup` szakaszában van (időpont, megőrzés, a második hely: `\\DS918plus\homes\kassaiattila\jav-ai-backup`, és 070 óta `with_docs`: a belső munkaanyag is).

```powershell
.\scripts\backup-task.ps1 install   # bejegyzés a Windows Feladatütemezőbe (naponta 12:00; kimaradáskor a következő bekapcsoláskor)
.\scripts\backup-task.ps1 status    # utolsó és következő futás, eredménykód
.\scripts\backup-task.ps1 run       # azonnali futtatás próbához
python -m jav.cli backup --scheduled # ugyanez kézzel: helyi mentés + ellenőrzött másolat a NAS-ra
python -m jav.cli backup --copy-to D:\Mentes   # egyszeri mentés tetszőleges második helyre
```

Az eredménykód 0, ha minden rendben; 1, ha a helyi mentés hibás; 2, ha a helyi mentés rendben van, de a másolat nem sikerült (például nem érhető el a NAS). Minden futás eredménye a `store\backups\backup-status.json`-ba kerül; a felület ebből mutatja az állapotot, és figyelmeztet, ha a legutóbbi sikeres mentés 36 óránál régebbi. A feladat a bejelentkezett felhasználó nevében, ablak nélkül fut. Ha a mentett másolat sértetlenség-ellenőrzése hibát jelez (066), a rendszer nem töröl régebbi mentést és nem másol a NAS-ra; a hibás mentés mappája a vizsgálathoz megmarad, és nem számít bele a megőrzésbe.

**Folyamatállapot-tár (064):** a feldolgozó minden lépés után menti a folyamat állapotát (`store\burr_state.sqlite`). Lezárt tételnél ebből csak az utolsó marad, mert a folytatáshoz csak az kell. A régi, ritkítás előtti tár egyszer ritkítható és tömöríthető:

```powershell
python -m jav.cli burr-prune          # ritkítás (futó feldolgozó mellett is), tömörítés csak leállított feldolgozóval
python -m jav.cli burr-prune --no-vacuum
```

**Visszaállítás (kézi):**

1. `.\scripts\dev.ps1 stop` (a szolgáltatás és a feldolgozó leáll);
2. a mostani `store\jav.sqlite` félretétele, például `store\jav.sqlite.hibas` néven; a mellette lévő `jav.sqlite-wal` és `jav.sqlite-shm` fájlt is át kell nevezni;
3. a kiválasztott mentés `jav.sqlite` fájljának visszamásolása a `store\` alá;
4. `.\scripts\dev.ps1 start`.

A mentés utáni futások, javítások és döntések a visszaállítással elvesznek. A letöltött levelek (`inbox\`) és a forrásiratok nincsenek az adattárban, ezeket a mentés nem érinti.

**A belső munkaanyag visszaállítása (070):** a mentés mappájában lévő `internal-docs.zip` a projektgyökérhez viszonyított neveket tartalmaz (`docs/handoffs/…`). Kibontás a projektgyökérbe, például `Expand-Archive store\backups\<időbélyeg>\internal-docs.zip -DestinationPath . -Force`. Ez felülírja az azonos nevű helyi fájlokat. Egy fájl régebbi változatához előbb egy üres mappába érdemes kibontani.

**Napló:**
- `runs\logs\api.log` a helyi szolgáltatásé, `runs\logs\worker.log` a feldolgozóé. Állandó, 5 MB-onként forgó fájlok, fájlonként 5 régi példánnyal. Ide kerül minden váratlan hiba teljes hibanyoma, a feldolgozó indulása és leállása, valamint a 404, 422 és 500 válaszok oka.
- A `runs\dev\*.log` az indítószkript átirányított kimenete; az előző indításé `*.prev` néven megmarad.
