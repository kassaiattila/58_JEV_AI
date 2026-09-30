# Jev-feltérképezés — mit tud a modell, mit használunk, mit vegyünk át (2026-09-20)

**Friss olvasási pont, 2026-09-21:** JEV-képességek a saját fejlesztési tapasztalatokkal összevetve (belső: `JEV_CAPABILITY_INTEGRATION_2026-09-21.md`), valós összehasonlító mérés (belső: `STACK_TRIAL_RESULTS_2026-09-21.md`).
Az alábbi rés-elemzés történeti kiindulás; a később elkészült adapter-, sáv-, regiszter- és kérdésfejlesztések a §4 dátumozott bejegyzéseiben szerepelnek. A sorösszefűzés, párosítás és hierarchia már kapott kis képességpróbát, de teljes integrációjuk nincs kész.
Pontosítás: a bemenet **és a kérdések** tokenjei költséget jelentenek; a kötegelés nem korlátlanul ingyenes. A gyorsítótáras visszajátszás nem élő determinizmusmérés. Az aktuális modellkorlátokat a fenti új értékelés élő hivatalos forrásokra hivatkozva rögzíti.

Forrás: a teljes `docs.typesafe.ai` (az `llms.txt` index 45 oldala: bevezető, koncepciók, primitívek, confidence, 4 minta,
modellek, jaggedness, SDK-referencia, 19 cookbook, demó), Markdownban letöltve és elolvasva; a cookbookok kivonatát két
párhuzamos ügynök készítette, a mag-oldalakat a szerző olvasta. Cél: a **keretrendszer** (nem a magyar számla) Jev-rétegének
megtervezése. A doksi élő forrás: `https://docs.typesafe.ai/<útvonal>.md`. Ez a fájl a tervezési alap; a döntéseket a
handoff és a ROADMAP rögzíti.

## 1. A modell tényei (jev-1.13.0 = `jev-latest`, 2026-09-17-i doksi-állapot)

| tény | érték | következmény nálunk |
|---|---|---|
| ár | $0,042 / M input token, output ingyen | a state-méret az egyetlen költség; kérdés hozzáadása majdnem ingyen |
| kontextus | 64k token kérésenként; 32k a state + a leghosszabb kérdés | egy teljes 1–3 oldalas PDF belefér; korpusz-szintű state nem |
| Choice-opciók | max 255 | jelölt-listák darabolása 255 fölött (sor-ablakok) |
| Score-szintek | 2–10, leírással; szám önmagában rossz | fokozatot Score-ral, nem Noullal |
| rate limit | 250k token/s, 1200 kérés/perc, **dinamikusan változik**; 429/529 → backoff | bejárásoknál 4–8 párhuzamos worker, explicit `RetryPolicy` |
| bemenet | csak szöveg (string / JSON / tömb) | OCR/kép a sidecar dolga (B5) |
| nyelv | angol az elsődleges; más nyelv „alacsonyabb pontosság, mérd magad" | a magyar/német verbatim state működését CSAK a saját golden bizonyítja, verziónként újra |
| alias | `jev-latest` mozog verzióváltáskor; a válasz `model` mezője a konkrét verzió | a ledgerbe a válasz-modell megy (már így van); a **cache-kulcsba ma az alias megy** → javítandó |
| testreszabás | nincs finomhangolás; state + instrukció + kritérium + kód-kompozíció | a „konfig mint adat" elvünk pontosan a doksi ajánlása |
| napló | `TYPESAFE_LOG_LEVEL=debug` kitakarás nélkül írja a body-t | PII: tiltani a `.env`-ben / adapterben |
| SDK 0.7.0 (2026-09-18) | Pydantic-alapú, `response_model`, `RetryPolicy`, `AsyncTypeSafeClient` | a lockolt verziónk 0.7.0 — friss |

**Jaggedness (a modell ismert gyengéi, doksi szerint):** szó szerint olvas; nem számol, nem hasonlít dátumot; indirekció
és dupla tagadás rontja; a nagy, irreleváns state ront („context rot"); adverzariális szöveg elmozdítja; instrukció és
kritérium ellentmondása zavarja; **nincs szerkezeti invariancia** (Noul ≠ Choice yes/no; P(noul) + P(nem-noul) ≠ 1;
Noul-küszöb nem vihető át Choice-ra); nem generál. Mindegyikre a válasz: kódban számolj, szűrj, bonts atomi kérdésekre.

## 2. Amit már a doksi szerint csinálunk (ellenőrzött)

- Egy kérés, sok független kérdés (fan-out): select 3 kötegelt kérés, verify egy battéria, detect és email_intent egy-egy
  kérés Choice + Noulokkal. ✔
- Jelöltek kódból, Jev választ, kód másol (pre-parsed value extraction cookbook = az S-kar). ✔
- Verify = SDE-cascade minta (mezőnkénti „bad = true" Noulok, kód-evidencia előtte, `max`-jellegű review-kapu). ✔ részben (ld. 4.)
- `none` / `unknown` / `other` minden Choice-ban; angol instrukció + glosszárium, magyar verbatim state; sor-azonosítók (`L01:`). ✔
- Nyers valószínűség a state-ben, küszöb a `policy.json`-ban; kérés-hash cache; ledger `config_hash`-sel. ✔
- Determinizmus-mérés cache nélkül (és mostantól cache-írás nélkül: `JevAdapter.no_cache_write()`). ✔

## 3. Rés-elemzés hívási helyenként (doksi-ajánlás → mai állapot → teendő)

| hely | doksi-ajánlás | ma | teendő |
|---|---|---|---|
| **adapter** (`adapters/jev.py`) | konkrét modellverzió a cache-kulcsban; explicit `RetryPolicy` időköltségvetéssel; kivétel → ledger (`status`, `retry_after_ms`), a flow ne dőljön el; async/ThreadPool bejárásnál; `response_model` típusos válaszhoz; `extra_body` átvezetés | alias a kulcsban; SDK-alapértelmezett retry; kivétel felfut; szekvenciális; nyers `SystemOneResponse` | 1. `models.list()`/válasz-modell a kulcsba; 2. retry-policy a `models.json`-ból; 3. kivétel-ledger + `needs_review:jev_unavailable`; 4. worker-pool a bejárásoknak |
| **policy** (`policy.py`, `policy.json`) | kétoldali sáv Noulra (no / uncertain / yes, pl. 0,3–0,7); küszöb a tét szerint (konf.-küszöb magasabb a nagy tétű akciónál); második opció P > 0,25 = review-ok; sorrendes, nevesített policy-készlet (strict / permissive) precedenciával; durvább szülő-címke alacsony confidence-nél | egy küszöb Noulra (`review_flag_p` 0,7); egy conf-floor 0,6; high-stakes lista van; nincs sáv, nincs szülő-címke, nincs nevesített policy | 5. sávok + második-opció szabály + policy-nevek a `policy.json`-ba; a régi `runs/*.jsonl` újraértékelhető hívás nélkül |
| **evals** (`evals*.py`) | per-kérdés szórás; „policy agree / uncertain / automatic / conflicts" oszlopok; kalibrációs görbe (bin: P vs találati arány); top-prob vs `confidence` küszöb összemérése; verziófüggetlen entrópia-confidence | flip-szám + conf-szórás; nincs kalibrációs riport | 6. közös eval-riport modul flow-független (ez a keret-szintű „measure"); 7. kalibrációs görbe a golden-futásokból |
| **detect** (M1) | strukturált opció-leírás `{what, not_for, examples}` az összetéveszthető pároknál; leírás = a kategória tartalma; spekulatív Noulok (több dokumentum egy PDF-ben, szkennelt, hitelesített másolat) ugyanabban a kérésben; szülő-szint (invoice_like / contract_like / bank_like / other) | egysoros angol leírás + anchor-feature; 1 Choice + 1 Noul + language | 8. regiszter-séma bővítés (`what/not_for/examples`, `parent`); mérés: detect-golden előtt-után, determinizmus |
| **email_intent** (M3) | ugyanaz a strukturált leírás; Score-jelek (sürgősség, hangnem 3–4 szint) a Noul helyett ahol fokozat kell; „több önálló kérés van-e" Noul → LLM-darabolás; promptinjekció-Noul minden gpt-hívás előtt; szándék-családok | Choice + 4 Noul; `tone_urgent` Noul | 9. regiszter-séma mint M1; `tone_urgent` → Score; injekció-Noul a G-kar és minden generatív hívás elé |
| **select** (M2 S) | „stated"/jelenlét-Noul minden opcionális mező mellé (nehogy magabiztosan rosszat válasszon, ha a mező nincs is a dokumentumon); rekord-confidence = min; sor-ID Choice + „létezik-e" Noul az evidencia-lokalizálásra; azonos formátumú mezőknél szerep-leírás | Choice jelöltek + `none`; nincs jelenlét-Noul; conf mezőnként | 10. jelenlét-Noul a három kötegbe; a kiválasztott érték sor-ID-je a `datapoints`-ba (forrás-hivatkozás a review-hoz) |
| **verify** (M2 G) | determinisztikus string-egyezés a Jev elé (van: `find_evidence`); strukturált Noul-instrukció `{field_spec, extracted_field, question}` az f-string helyett; `supports / contradicts / says_nothing` Choice ahol az ellentmondás külön kezelendő; kimeneti battéria: „ad-e mezőt, ami nincs a dokumentumban" | f-string sablon `{field} {spec} {value}`; 7 Noul-fajta; evidencia kódból ✔ | 11. instrukció objektum-formára (új cache-kulcs → golden újra); kétoldali sáv a flagekre (5.) |
| **pdf / tételsorok** | Noul-pár sor-összefűzés írásjel-függő küszöbbel (autoformat); blokk-típus Choice + kísérő kérdések előre | szó-szintű rekonstrukció, nincs Jev a rétegzésben | B1 bővítés terve; nem most |
| **párosítás / dedup** (B3) | 3 szintű Score (nem az / talán / ez az) + mezőnkénti Noulok egy kérésben; a középső szint = kurátor; számot kódban hasonlíts; kód-shortlist + páronkénti Noul re-rank, ha > 255 jelölt | — | B3 terve |
| **ML-kapu** (B2) | Jev-jelek (várható érték + szórás oszlop) + kód-feature-ök → CatBoost, k-fold, holdout érintetlen; a proposer-loop csak több száz címkével | — | B2 terve; előfeltétel: review-döntések mint címkék |
| **hierarchia** (B4) | Choice szintenként, opció = gyerek-részfa; beam K=2–3; geometriai-átlag pontszám; `separation` = review-ok | — | B4 terve (számlatükör) |

## 4. Prioritált backlog a keretrendszerhez (javaslat, egyeztetendő)

A sorrend elve: **előbb a keret-szintű, flow-független elemek** (adapter, policy, eval, regiszter-séma), mert ezek minden
jövőbeli flow-t szolgálnak; a hívási hely-finomítások utána, mindig golden-méréssel; a bővítések (B1–B5) csak tervként.

**Állapot 2026-09-20, handoff 010: a 6. tétel (verify strukturált Noul-instrukció) kész** — `configs/callsites/verify.json`
v1.1.0, `{glossary, field_spec, extracted_field, printed_on, question}` objektum; az ellenőrző-szonda nyers futást ír,
sáv szerint összegez (kétoldali sáv a flagekre), telefonszám-variánssal; mérés a README „G-kar ellenőrző kérdések
szerkezetes formában” szakaszában (kis javulás: 2 elrontás a bizonytalanból az igen-sávba, 0 hamis riasztás).
**Handoff 011: a 7. tétel (M3 jelek) is kész** — `configs/callsites/email_intent.json` v1.1.0: `urgency` Score (4
helyzet-szint) a `tone_urgent` Noul helyett, `multiple_requests` Noul (csak mérhető), `prompt_injection` Noul
(`policy.json` v1.4.0: `signal_review` + `signal_routes` → `human:suspicious`); `email-injection-probe`; mérés a README
„M3 jelek” szakaszában (golden 96/96, 0 flip, a levél elejére tett utasítás 24/24, a tisztító mögé tett vak — az
őr-kérdés hatóköre = a döntés hatóköre). Ezzel a §4 hívási hely-tételei (5–7) mind készek; a sorrend innen: 9 (B1–B4
tervek) a keret-recept után.

**Állapot 2026-09-20 (keret-kör 1, handoff 006):** az 1–3. tétel kész (`jav/adapters/jev.py`, `configs/policy.json`
v1.1.0 + `jav/policy.py`, `jav/eval_report.py` — részletek a README „Jev keret-kör 1” szakaszában). Tanulság a
doksihoz képest: a `models.list()` **csak aliasokat ad** (`jev-latest`, `jev-preview`), a konkrét verzió csak a válasz
`model` mezőjéből olvasható → az adapter szondával oldja fel. A worker-pool (1/4) elhalasztva. A 8. tétel (checklist)
a CLAUDE.md §4-ben már benne van. **A 4. tétel (regiszter-séma v2) is kész** ugyanaznap (handoff 007): `what / not_for /
examples / parent`, strukturált Choice-kritérium (`jav/registry.py`), szülő-család kódban összegezve, `parent_min_prob`
sáv-küszöb; mérés a README „Regiszter-séma v2” szakaszában. **Az 5. tétel (jelenlét-Noul az S-karban) is kész**
(handoff 008): `<mező>__present` Noul a három kötegelt kérésben, `present_p` + `line_no` a pickben, rekord-conf = min,
`evidence` a `datapoints`-ban; mérés a README „S-kar jelenlét-Noul” szakaszában. A sorrend innen: 6–7.

| # | tétel | szint | forrás | mérés / bizonyíték |
|---|---|---|---|---|
| 1 | **Adapter-korszerűsítés**: konkrét modellverzió a cache-kulcsban (`models.list()` induláskor, a válasz `model`-je), explicit `RetryPolicy` a `models.json`-ból, kivétel → ledger + `needs_review:jev_unavailable`, `TYPESAFE_LOG_LEVEL` védelem, opcionális worker-pool a bejárásoknak | keret | api, models, sdk/retries, exceptions | teszt hamis klienssel; golden mind cache-találat (tartalom-semleges) |
| 2 | **Policy-séma általánosítása**: Noul-sávok (no/uncertain/yes), második-opció küszöb, tét-szerinti conf-küszöb, nevesített policy-készlet precedenciával, hívási helyenként; a route-döntés a nyers jelekből | keret | confidence, confidence-routing, consistency_noul, llm_guardrails | a meglévő `runs/*.jsonl` újraértékelése hívás nélkül: hány eset vált sávot |
| 3 | **Közös eval-modul**: per-kérdés szórás, policy-agree / uncertain / automatic / conflicts, kalibrációs görbe (bin-enként P vs. találat), top-prob vs. confidence; flow-független bemenet (jsonl) | keret | consistency_choice, parallel_questions, ML-primer | a 4 meglévő golden-futásból riport |
| 4 | **Regiszter-séma v2** (`doc_types`, `intents`): `what / not_for / examples / parent` mezők, a Choice-kritérium ebből épül; a few-shot csak goldennel konzisztensen | keret | primitives/choice, advanced, classification_using_confidence | detect-golden 49, intent-golden 96 előtt-után + determinizmus; szülő-címke arány a < 0,6 sávban |
| 5 | **Jelenlét-Noul az S-karban** (mezőnként „szerepel-e egyáltalán") + rekord-conf = min + sor-ID a datapoints-ba | hívási hely | function_calling, semantic_find | golden S 12 eset: a `none`-döntések és a review-arány változása |
| 6 | **Verify strukturált instrukció** (`field_spec / extracted_field / question` objektum) + kétoldali sáv a flagekre | hívási hely | primitives/noul, sde_cascade | verifier-probe (injektált hibák) előtt-után |
| 7 | **M3 jelek**: `tone_urgent` → Score, „több kérés van-e" Noul, injekció-Noul a generatív hívások elé | hívási hely | primitives/score, smart-home, classifying_rag | intent-golden + élő 103 levél |
| 8 | **Jev-checklist bővítése a CLAUDE.md-ben** (5. szakasz) | módszer | jaggedness, több cookbook | — |
| 9 | B1 tételsorok (autoformat-minta), B3 párosítás (entity_alignment + rerank), B2 ML-kapu (autoresearch), B4 hierarchia (hierarchical_classification) | bővítés | cookbookok | tervezéskor a cookbook újraolvasása |

Ami **nem** kell: Jev generálásra; Noul fokmérőnek; szám- és dátum-összevetés a modellel; egy kérdésbe rejtett több ítélet.

## 5. A Jev-checklist bővítése (javasolt sorok a CLAUDE.md §4-be)

- A kérdés a legszűkebb eldöntő tényt nevezze meg; ha egy rossz válasznál „amit igazából kérdezni akartam"-mal magyarázol,
  az a hiányzó fél mondat az instrukcióból.
- Choice-leírás = a kategória tartalma és amit NEM fed (`what / not_for / examples`); Score-szint = konkrét helyzet, nem fok.
- Fokozathoz Score (≤ 10 szint), igen/nemhez Noul, rendezett háromkimenetű döntéshez (nem az / talán / ez az) Score.
- Noul-küszöb kétoldali sáv; a Noul- és a Choice-küszöb nem cserélhető; ne várj aritmetikai azonosságot kérdések közt.
- Minden opcionális mező Choice-a mellé jelenlét-Noul; rekord-confidence = a leggyengébb ítélet.
- State: csak amit a kérdés használ; a szám- és dátum-aritmetika, a string-egyezés kódban, előtte.
- Konkrét modellverzió a mérésekben; a kalibráció verziónként újramérendő; a magyar/német pontosság csak saját goldennel bizonyított.

## 6. Amit a doksi nem mond ki (saját méréssel pótolandó)

- A nem-angol state pontossága: nincs szám; nálunk 100 % a 12+49+96 eseten — kicsi minta, in-sample finomítással.
- A `confidence` képlete nem publikus („a doksi külön cookbookot ígér"); a migrációs oldal régi képlete (1 − normalizált
  entrópia) számolható a `probabilities`-ből → verziófüggetlen mérőszám a riportokba.
- A rate limit és a `jev-latest` mögötti verzió változhat előzetes jelzés nélkül → a ledger válasz-modellje az igazság.
