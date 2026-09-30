# CLAUDE.md

Állandó munkaszabályok a Claude Code számára ebben a repóban. **Session-állapot, haladás és mérési szám nem ide kerül.** Az aktuális állapot helyei: a legfrissebb `docs/handoffs/NNN-*.md`, a generált `docs/STATE.md`, a `docs/BACKLOG.md` és az aktuális terv (`docs/INDEX.md` → „Aktuális munka”). Ezek **belső munkaanyagok** (070): csak helyben vannak, a git nem követi őket, friss klónban nincsenek meg. A dokumentumok rendjét a [docs/guides/DOCUMENTATION.md](docs/guides/DOCUMENTATION.md), a git-munkamenetet a [docs/guides/DEVELOPMENT.md](docs/guides/DEVELOPMENT.md) írja le.

## 1. Mi ez a projekt

Általános, többnyelvű **dokumentum- és e-mail-feldolgozó AI-flow-keretrendszer**: Burr (folyamatvezérlés) + Pydantic AI (GPT) + JEV/TypeSafe (típusos ítéletek), helyi SQLite-tal. A magyar számla-flow-k (**M1** kategorizálás, **M2** adatpont-kinyerés, **M3** e-mail szándék) **referencia-flow-k**: ezeken mérjük a keret minőségét. Új képességnél a keret-réteget általánosítsd, ne a számla-specifikus kódot bővítsd. Kiegészítő cél: új dokumentumtípus megtanítható legyen, és ismeretlen szöveg adatpontjai is strukturáltan tárolódjanak.

- **Nyelv:** a felhasználóval magyarul. Kód és azonosítók angolul, kommentek és dokumentáció magyarul.
- **PII** (valódi irat, levél, golden-tartalom) soha nem kerül gitbe, csak sha256 + útvonal. Új teszt csak mesterséges vagy anonimizált adattal készülhet.
- **Régi projekt:** `C:\00_DEV_LOCAL\10_AIFLOW_V4`, csak olvasásra (lásd 3. pont). Burr-natív, a 2026-09-09-es állapotában LangGraph is van benne. Nem Langflow, hiába nevezi így a felhasználó.

### Állandó felhasználói keretek (részletek és dátumok: `docs/DECISIONS.md`, ne nyisd újra)

- OpenAI és JEV egyaránt használható a már engedélyezett dokumentum- és e-mail-mintákon. Általános szolgáltatói engedélyt ne kérj újra.
- Összkeret: **9 USD OpenAI + 9 USD JEV** (az eredeti 5 + 5, 2026-09-28-án +4 + 4). A maradék az aktuális elszámolási fájlban van (hivatkozás a legfrissebb átadóban). Új méréshez előre rendelj részkeretet ezen belül; régi kereteket ne vonj össze és ne emelj meg hallgatólagosan.
- Kézi címkézés elhalasztva, nem előfeltétel. Modell-egyetértést ne nevezz pontosságnak.
- Vállalati és termékesítési feladatok (SSO/RBAC, tenant, HA, árazás) most nem prioritások.
- Üzemi küszöb, policy vagy folyamat aktiválása csak felhasználói döntéssel történhet.

## 2. Session-protokoll (a felhasználó kifejezett kérése)

1. **Indulás = helyzetfelmérés, nem kódolás.** Futtasd: `python -m jav.cli preflight`, `git status`, `git log --oneline -10`. Olvasd el a legfrissebb átadót (a SessionStart-hook betölti), a `docs/STATE.md`-t, a `docs/BACKLOG.md`-t, a `docs/DECISIONS.md` végét és az aktuális tervet. Utána 5–8 soros összefoglaló a 8. pont váza szerint, nyitott döntésekkel és javasolt sorrenddel, és **kérdezd meg a felhasználót, egyetért-e**, mielőtt építesz.
2. **Önálló szakmai ítélet.** Egy korábbi terv vagy átadó bemenet, nem parancs. Ellenőrizd a kódon és a mért tényeken. Ha eltérsz tőle, mondd ki és indokold.
3. **Git.** A `main` mindig zöld. Szakaszonként külön ág, kis commitok, a teszt és a kódtári dokumentáció a kóddal egy commitban. A belső munkaanyag (átadók, tervek, jelentések, BACKLOG, DECISIONS, ROADMAP, INDEX, `docs/callsites/`; lista: `jav/doc_scope.py`) nem kerül commitba, és kódtári dokumentum nem linkel rá (DOCUMENTATION §1.7). A formátum és a címkék a DEVELOPMENT útmutatóban vannak. Commit előtt `preflight --skip-pytest` + érintett tesztek, beolvasztás előtt teljes `preflight`. Commit és feltöltés előtt az adatőr fut (`hooks-install`, DEVELOPMENT §1); a `--no-verify` tilos. Távoli tárolót csak felhasználói döntéssel használj. Az `origin` (GitHub, 2026-09-29) csak a 2026-09-30-i második kiindulópont utáni történetet kapja. Az `archiv/elotortenet-069` és az `archiv/elotortenet-070` ágat, a 070 előtti szakasz-ágakat és a régi címkéket soha ne töltsd fel, mert személyes adat, illetve belső munkaanyag van bennük. `--all` / `--tags` / `--mirror` tilos; a helyi `pre-push` horog ezt elutasítja (DEVELOPMENT §1).
4. **Átadó** (`docs/handoffs/NNN-ÉÉÉÉ-HH-NN-handoff.md`, sablon: `TEMPLATE.md`, a korábbiakat nem módosítjuk). Új átadó csak a session végén és szakasz lezárásakor kell (2026-09-27-i döntés; a finom történetet a git viszi). Szakaszzárásnak számít egy lezárt mérés is, session-végnek az is, ha a kontextus nagyjából félig megtelt. Tartalom: mi készült (táblázat), felhasználói döntések dátummal (ugyanazok a `DECISIONS.md`-be is), mérések bizonyítékhivatkozással, nyitott kérdések, következő lépés, csapdák, **commit hash**. Az átadó helyben marad, nem commitoljuk (070). Állapotszámot kézzel ne másolj, a `STATE.md`-re hivatkozz.
5. **Hookok** (`.claude/settings.json`, `scripts/hooks/handoff_guard.py`): SessionStart betölti az átadót és kiírja a git-állapotot; PreCompact figyelmeztet; a Stop elavult átadónál frissíti a `STATE.md`-t és **nem blokkoló** emlékeztetőt ad (commitolatlan fájlok, commitok száma az átadó óta; 2026-09-27-i döntés); PostToolUse alatt egy Fable review-ügynök ellenőrzi az átadót, és a hibáit javítani kell.
6. **Döntést a felhasználó hoz.** Policy-kérdésben (típushatár, sorrend, osztálykészlet, keret) `AskUserQuestion`-t használj opciókkal és ajánlással. A döntés az átadóba, a `DECISIONS.md`-be és a memóriába kerül, dátummal.

## 3. Újrahasznosítás: előbb keress, csak aztán írj

Építés előtt nézd meg, megvan-e a régi projektben: `scripts/` (pl. `outlook_bridge.ps1`), `flows/*-bare/` (flow + CONTRACT + golden), `orchestrator/framework/` (jobq, tabular, businessworkflows…), `sidecar/app/`, `ui/src/` (viselkedési minták és tesztek), `data/golden/`, `.planning/`. Ami megvan, azt hivatkozd (útvonal a `jav/config.py`-ban), vagy portold célzottan, származási bejegyzéssel. A saját kódban is bővíts, ne duplikálj. Futtatókörnyezetből tilos `sys.path`-trükkel a régi orchestratort importálni vagy a régi üzemi adatbázist olvasni. Az átadóban mondd ki a döntést: „megvolt / portoltam / új, mert…”.

## 4. Fejlesztési szabályok

- **Eszközválasztás mérés alapján.** Pontos számítás, formátum- és forrásegyezés kódban történik. GPT és JEV külön vagy együtt használható értelmezésre, kinyerésre, kategorizálásra és ellenőrzésre. A szereposztást mérés dönti el: helyesség, teljesség, hibás elfogadás, robusztusság, késleltetés és költség alapján. Modell-egyetértés és JEV-támogatás nem független helyességi bizonyíték. Új JEV-kérdésnél olvasd a `docs.typesafe.ai` releváns részét.
- **JEV-ellenőrzőlista** (részletek: `docs/JEV_PLAYBOOK.md`):
  - Angol instrukciót és glosszáriumot írj; a state verbatim szöveg, magyarul vagy angolul.
  - Mindig legyen `none`/`unknown`/`other` válasz, a Choice legfeljebb 250 opciós, a jelöltek dedupolva.
  - Few-shot példa csak akkor kerülhet be, ha a goldennel konzisztens.
  - A kérdés a legszűkebb eldöntő tényt nevezze meg.
  - Choice-leírás: `what / not_for / examples`. Fokozathoz Score kell (≤ 10 szint), igen/nemhez Noul kétoldali sávval.
  - Minden opcionális mező mellé jelenlét-Noul kell. A rekord-confidence a leggyengébb ítélet.
  - Szám, dátum és string-egyezés kódban történik, a kérdés előtt. A mérésben a konkrét `model` verzió számít, nem az alias.
- **Nyers valószínűség a state-ben, küszöb csak a `configs/policy.json`-ban** (`jav/policy.py`). A review-latch additív: a `needs_review` csak False→True irányban változhat. A `run_id` a gerinc. Minden AI-hívás a ledgerbe kerül, a hibás is. `JevUnavailableError` esetén `jev_unavailable:<ok>` review kerül a sorba, a flow nem dől el. Pénz: `Decimal`.
- **Konfig mint adat.** Típus- és szándékregiszter, instrukció, séma és küszöb JSON-ban van, verziózva (`meta`), a `config_hash` a ledgerbe kerül. Konfigváltozás után: verziólépés, golden-futás, `python -m jav.cli docs`.
- **Burr-gráf = kontraktus.** A fázisok, lépések és élek adatszerkezetben vannak; ebből generálódik a `FLOW.md` és a Mermaid-ábra, és lint ellenőrzi az egyezést. Új keret-modul csak akkor készül, ha két flow már kézzel ugyanazt írta le.
- **Mérés előtt és után.** Regiszter-, instrukció- vagy küszöbváltozás után golden-futás kell. Determinizmus mindig `use_cache=False` és `no_cache_write()` mellett mérhető. A tanító példákon mért finomítást mondd ki. Kódváltozás előtt `recall` + `pytest`, TDD. Élő, fizetős mérés csak tiszta munkafán, a commit hash rögzítésével indulhat.
- **Diagnózis sorrendje:** `runs/*.jsonl` → `--no-cache` futás / `verifier-probe` → csak ezután jöhet instrukció- vagy leírásmódosítás, általános szabályként, nem fixture-hackként.
- **Kódminőség.** Új vagy érdemben módosított kód Ruff-tiszta, wildcard import és elnyelt kivétel nélkül. A publikus művelet típusos be- és kimenettel, nevesített hibával készül. Függési irány: felület/CLI → alkalmazási művelet → üzleti modul/runtime → adapter/adattár. Kísérleti kódot futtatókörnyezet nem importál.

## 5. Parancsok

Aktivált venv: `.\.venv\Scripts\Activate.ps1`, anélkül `.venv\Scripts\python.exe`. Telepítés: [docs/guides/SETUP.md](docs/guides/SETUP.md).

```powershell
python -m jav.cli preflight [--skip-pytest]      # session-indítás: pytest + kontrakt-lint + konfigok + handoff + STATE.md
pytest tests/                                     # offline tesztek; egy teszt: pytest tests/test_emails.py -k next_flow
python smoke_test.py                              # venv + kulcsok + élő JEV-hívás
python -m jav.cli recall | golden --arm S|G | determinism --arm S --n 5 | verifier-probe [--no-cache] [--type invoice_foreign]
python -m jav.cli detect <pdf> | detect-golden | detect-determinism --n 3 | detect-corpus <mappa> [--redo-unknown] | detect-sample <mappa>
python -m jav.cli email <mappa> | email-golden | email-determinism --n 3 | email-inbox inbox/ | email-sample | email-injection-probe
python -m jav.cli email-ingest-server --port 8931 --run   # fogadó a régi outlook_bridge.ps1-hez (8901 = régi Docker)
python -m jav.cli recipes | wp-* | run-* | worker [--once] | worker-status | worker-stop   # munkacsomag → futás (jav/work_cli.py)
python -m jav.cli calls-uncertain | calls-resolve <id> [--cost USD] --note N   # bizonytalan kimenetű fizetős hívás kézi rendezése
.\scripts\dev.ps1 start|status|stop                     # felület + helyi szolgáltatás (serve, 127.0.0.1:8930) + egy feldolgozó
cd ui; npm run build | npm test | npm run dev             # felület (ui/): build a ui/dist-be, vitest, fejlesztői szerver :5173
python -m jav.cli ocr [<pdf>] [--force] [--psm N] [--limit N]   # PDF nélkül: az OCR-motor állapota
python -m jav.cli store | eval-report [runs/*.jsonl] [--out f] | admin [--write] | configs | flows [--check] | docs
python -m jav.cli hooks-install | data-guard [--all]        # 071 adatőr: git-horgok bekapcsolása (klónonként egyszer) | a verziókövetett fa átnézése
python -m jav.capability_catalog                  # determinisztikus típus-/intent-leltár
```

`JAV_OCR_ENGINE=azure_di <parancs>`: Azure DI a régi sidecaron át. **Fizetős**, oldalkeretes, az `auto` sosem választja. Élő Outlook-lekérés: a régi bridge változatlanul, a pontos parancs a README e-mail-szakaszában van. Kulcsok a `.env`-ben (`TypeSafeJAV_API_KEY`, `OPENAI_API_KEY`); értéket soha ne írj ki.

## 6. Architektúra (részletek: `docs/ARCHITECTURE.md`)

- **Munkacsomag → futás → feldolgozó → felület** (040 K1–K3): a munkacsomag, a recept (`configs/recipes.json`), a készenlét, a futás és a jóváhagyás a `jav/work.py`-ban; a futás tételei a tartós munkasorba kerülnek (`jav/runtime/queue.py`), a feldolgozó (`jav/runtime/worker.py`, egypéldányos zár: `lock.py`) Burr-állapotmentéssel (`persistence.py`) futtatja az alábbi gráfokat; minden fizetős hívás a futás keretéből foglal és a hívásnaplóba kerül (`jav/runtime/calls.py`). A felület (`ui/`, React) és a parancssor a helyi szolgáltatáson (`jav/api.py`, közös nézetek: `jav/work_views.py`) át ugyanazt a műveletet hívja; a szolgáltatás nem futtat, csak sorba tesz és olvas.
- **Burr-gráfok** (`@action.pydantic`, lokális tracker, `run_id` = app_id):
  - `jav/flow.py` (M2, S- és G-kar, típusfüggetlen; a típuscsomag `configs/types/<típus>.json` + `jav/typepack.py`, öröklés `extends`-szel);
  - `jav/flow_detect.py` (M1);
  - `jav/flow_email.py` (M3, a csatolmányokon az M1-et hívja);
  - `flow_learning.py`, `flow_email_learning.py` (tanulási ágak).
- **S-kar:** a kód jelöltet talál (`candidates.py`), a JEV Choice választ, mezőnként jelenlét-Noullal (`jev_select.py`). **G-kar:** GPT-kivonat (`extract_llm.py`) + JEV Noul-ellenőrzés (`jev_verify.py`). Egyetértés esetén auto, eltérés esetén review. A háló a `validators.py`.
- **Minden JEV-hívás** a `jav/adapters/jev.py` `ask()`-on megy át: kérés-hash cache a konkrét modellverzióval, RetryPolicy, ledger, költség. SDK-hiba esetén `JevUnavailableError`. A flow-k soha nem hívnak SDK-t közvetlenül.
- **OCR:** `ocr_pdf` lépés (`jav/ocr.py`, `configs/ocr.json`): natív tesseract, gyenge eredménynél Azure-eszkaláció (`ocr_with_escalation`). Az evalok a `jav/pdf.py: read_document()`-et használják, eszkaláció nélkül.
- **Regiszterek:** `doc_types.py` (12 típus + unknown), `intents.py` (a régi 11 szándék); elemenként `what / not_for / examples / parent`. Routing kódban: `policy.py` (`decide`, `email_next_flow`). A részletes típusleltár: `configs/capability_catalog.json` (23 séma, 11 aktív intent).
- **Store:** `store/jav.sqlite` (`store.py`): documents · datapoints · emails · review_queue · ledger · golden_labels. A golden a régi projektben marad, csak hivatkozva.
- **Evalok:** `evals*.py`, közös riport `eval_report.py`; nyers futások `runs/*.jsonl`. Kísérletek: `jav/experiments/` + `configs/experiments/`.
- **E-mail bemenet:** régi `outlook_bridge.ps1` → `jav/ingest_server.py` → `inbox/<mailbox>/<msgid>/message.json`.

## 7. Csapdák

- **Kódolás:** Windows cp1252/cp1250 esetén UTF-8 kimenet kell (`jav/__init__.py`). Fájlt Pythonból `encoding="utf-8"`-tel írj. A repó egységesen LF sorvéget használ (`.gitattributes`). Szöveges fájl kiírásakor figyelj, hogy ne legyen CRLF és ne sérüljenek az ékezetek: a döntésnapló két szakasza egyszer már „?”-re sérült.
- **Shell:** PowerShell 5.1-ben nincs `&&`, és a nem ASCII string-literál kerülendő. A PowerShell-változónév nem különbözteti meg a kis- és nagybetűt, ezért egy belső `$action` felülírja a `$Action` paramétert. Bash-heredocban a `\n` és a `\\` torzulhat, ezért kódfájlt Write/Edit eszközzel írj.
- **PDF és OCR:**
  - A `pdfplumber layout=True` ragaszt, ezért szó-szintű rekonstrukció kell (`jav/pdf.py`). Törött font esetén OCR jön; ha az sem ad szöveget, `needs_ocr`.
  - A tesseract nincs a PATH-on. A magyar csomag csak a `tools/tessdata`-ban van (`--tessdata-dir`). A `tsv` kimenethez a `-c tessedit_create_tsv=1` kapcsoló kell.
  - A régi sidecar Docker-OCR-je kb. 30× lassabb, csak tartalék.
- **JEV:**
  - Sok jelölt és hosszú state esetén `max_tokens_exceeded` (400) jön; ilyenkor a hívási hely `request_char_budget` / `option_context_max` beállításai segítenek.
  - A „másfajta szám” (pl. telefonszám adószámként) csak 0,57–0,63 valószínűséget kap, ezért ellenőrzőszám-validátor kötelező.
  - A Choice-kritérium bármely változása új cache-kulcsot ad, vagyis minden eset élő hívás lesz. Determinizmus-mérésben két regiszterváltozatot ne keverj.
- **Burr:** `[tracking-client,tracking-server]` + `loguru` kell hozzá. A `[start]` extra streamlitet húz be.
- **Adatok:** a régi inbox-mappák csak csatolmányt tartalmaznak, a törzsek a régi Postgresben maradtak. Markdown-táblás kézi címkézés nem működik; címkézni csak teljes szöveges nézettel lehet.
- **Dokumentumok:** a `docs/handoffs/TEMPLATE.md` nem átadó. A `docs/STATE.md` generált, kézzel ne szerkeszd. A belső munkaanyag módosítása nem jelenik meg a `git status`-ban; attól még el kell végezni (teendőlista, döntésnapló, átadó), és a napi mentés viszi. **Ne válts (`git switch` / `checkout` / `merge`) olyan commitra vagy ágra, amely a belső fájlokat még követi** (az archív ágak, a `00cea07` előtti commitok): a git a helyi belső fájlokat felülírja, visszaváltáskor pedig törli (2026-09-30-án megtörtént, a `8fd53bc`-ből helyreállítva). Régi állapotot `git show <commit>:<útvonal>` vagy külön munkafa (`git worktree add`) mutat; előtte `backup --with-docs`. A 036-os befagyasztott fájllista (223 hash) csak a régi mérésekre érvényes; új mérést commit hash azonosít.

## 8. Kommunikáció és dokumentáció a felhasználó felé (2026-09-20, a felhasználó kérése — kötelező)

A felhasználó visszajelzése szerint a definiálatlan szakszavak, a kontextus nélküli számok és a prózába kevert kód-azonosítók miatt nem tudja terelni a munkát. Ezért minden neki szóló szöveg (chat-válasz, átadó, README-szakasz, döntés-kérdés) ezt a rendet követi:

1. **Fogalomtár az egyetlen szótár** (`docs/GLOSSARY.md`). Új fogalom csak akkor kerülhet szövegbe, ha előbb a fogalomtárba került. Első előfordulásakor fél mondattal magyarázd meg, vagy hivatkozz a fogalomtárra.
2. **Kötelező váz:** (a) mi volt a cél, egy hétköznapi mondatban; (b) mit csináltunk, mit tud most a rendszer; (c) mit jelent az eredmény, a számok viszonyítással; (d) mi a döntés vagy kérdés, opciókkal és ajánlással; (e) csak ezután, „Technikai részletek” cím alatt jöhetnek a fájlnevek, parancsok, verziók.
3. **Kód-azonosító a prózában tilos.** Kivétel a Technikai részletek blokk és a dokumentumok technikai szakaszai. A prózában a dolgot a szerepe szerint nevezd meg magyarul.
4. **Szám csak jelentéssel:** mit mér, mihez képest, mi következik belőle. Százalék mellé a darabszámot is add meg.
5. **Hossz:** a chat-összefoglaló legfeljebb 10 mondat a Technikai részletek előtt, ami több, az dokumentumba kerül. Az átadó és minden README-szakasz „Laikus összefoglaló” bekezdéssel indul (3–5 mondat).
6. **Angol kifejezés** csak JEV-doksi- vagy kódnévként szerepelhet (Choice, Noul, Score), magyar magyarázattal.
7. **Ha a felhasználó azt mondja, nem érti,** ne magyarázkodj: írd újra a fogalomtár nyelvén, és a hiányzó szót vezesd be a fogalomtárba.
