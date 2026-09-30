// Feliratok: állapotok, teendő-okok, mezők. A kódok a szolgáltatásból jönnek; itt csak megjelenítés.
// 057: a felirat a választott nyelven (i18n `t()`); a magyar szöveg a kulcs. A címkeszótárak (`tmap`) olvasáskor
// fordítanak, így a hívó helyeken nem kell változtatni; a komponensek a `useLocale()`-lal frissülnek.

import fieldLabels from "../../configs/field_labels.json";
import intentRegistry from "../../configs/intents.json";
import emailTasks from "../../configs/email_tasks.json";
import type { Recipe } from "./api";
import { getLocale, t } from "./i18n";

/** Címkeszótár, amely olvasáskor fordít (`MAP[kód]` → a választott nyelven). Az `Object.entries` a magyar forrást adja. */
export function tmap(source: Record<string, string>): Record<string, string> {
  return new Proxy(source, { get: (o, k) => (typeof k === "string" && typeof o[k] === "string" ? t(o[k]) : Reflect.get(o, k)) });
}

export const RUN_STATUS: Record<string, string> = tmap({
  queued: "Sorban áll",
  running: "Fut",
  needs_review: "Teendő vár",
  done: "Kész",
  failed: "Hibás",
  cancelled: "Leállítva",
});

export const ITEM_STATUS: Record<string, string> = tmap({
  done: "Lefutott",
  failed: "Hibás",
  cancelled: "Leállítva",
  needs_review: "Teendő",
  needs_ocr: "OCR kell",
});

export const FINAL_STATUS: Record<string, string> = tmap({
  done: "Lezárva, teendő nélkül",
  needs_review: "Teendő",
  needs_ocr: "OCR kell",
  jev_unavailable: "JEV nem volt elérhető",
});

export const MODE: Record<string, string> = tmap({ shadow: "Próba", apply: "Éles" });

// 056 U1: a mezők és a listaoszlopok magyar neve a configs/field_labels.json-ban van — ugyanazt olvassa a szolgáltatás,
// így a szolgáltatás oldali keresés és rendezés is a magyar névre megy. 057: a 23 irattípus neve is itt van.
export const FIELD: Record<string, string> = tmap(fieldLabels.fields);
export const DOC_TYPE: Record<string, string> = tmap(fieldLabels.doc_types);

export const fieldLabel = (f: string) => FIELD[f] ?? f;
export const docTypeLabel = (d: string) => DOC_TYPE[d] ?? d;

/** Tételes lista oszlopa (és a felsorolt értékek: `oszlop=érték`). Ismeretlen névnél maga a név. */
const COLUMN: Record<string, string> = tmap(fieldLabels.columns);
export const columnLabel = (c: string) => COLUMN[c] ?? c.split("=").pop() ?? c;

/** Levél javasolt következő lépése (a szolgáltatás útvonal-kódja, 048 T2). */
export function nextFlowText(code: string | null | undefined): string {
  if (!code) return "–";
  const [kind, what] = code.split(":");
  if (kind === "m2") return what === "needs_ocr" ? t("Csatolmány: szövegfelismerés kell") : t("Adatkinyerés a csatolmányból ({{what}})", { what: docTypeLabel(what) });
  if (kind === "m1") return t("Csatolmány: típusfelismerés");
  const archive = tmap({ payment_proof: "fizetési igazolás", calendar: "naptár", order_status: "rendelés állapota" });
  if (kind === "archive") return what ? t("Archiválás ({{what}})", { what: archive[what] ?? what }) : t("Archiválás");
  const human = tmap({ inbox: "Kézi feldolgozás", fetch_document: "Kézi: a számla feldolgozása",
    low_confidence: "Kézi ellenőrzés: bizonytalan szándék", jev_unavailable: "Kézi ellenőrzés: a JEV nem volt elérhető",
    suspicious: "Kézi ellenőrzés: gyanús tartalom" });
  if (kind === "human") return human[what] ?? t("Kézi feldolgozás");
  return code;
}

const INTERVAL_NAMES = tmap({ "15": "15 percenként", "30": "félóránként", "60": "óránként", "240": "4 óránként", "1440": "naponta" });
/** Gyakoriságok a választott nyelven (függvényként, hogy nyelvváltáskor frissüljön). */
export const intervals = (): [number, string][] => [15, 30, 60, 240, 1440].map((m) => [m, INTERVAL_NAMES[String(m)]]);
export const intervalText = (min: number) => intervals().find(([m]) => m === min)?.[1] ?? t("{{min}} percenként", { min });

const CHECK_TEXT: Record<string, string> = tmap({
  "balance.discontinuity": "A futó egyenleg megszakad",
  "balance.opening_unparseable": "A nyitó egyenleg nem értelmezhető",
  "balance.amount_unparseable": "Egy tranzakció összege nem értelmezhető",
  "balance.running_unparseable": "Egy tranzakció egyenlege nem értelmezhető",
  "closing.mismatch": "A nyitó egyenleg + tranzakciók nem adják ki a záró egyenleget",
  "closing.unparseable": "A nyitó vagy a záró egyenleg hiányzik / nem értelmezhető",
  "closing.amount_unparseable": "Egy tranzakció összege nem értelmezhető",
  "totals.mismatch": "Az összesített terhelés / jóváírás nem egyezik a tranzakciókkal",
  "totals.amount_unparseable": "Egy tranzakció összege nem értelmezhető",
  "totals.unparseable": "A nettó, ÁFA vagy bruttó összeg hiányzik",
  "dates.out_of_period": "Tranzakció a kivonat időszakán kívül",
  "dates.due_before_issue": "A fizetési határidő korábbi a kiállításnál",
  "dates.unparseable": "A dátumok nem értelmezhetők",
  "taxid.checkdigit": "Az adószám ellenőrző számjegye hibás",
  "taxid.unrecognized": "Az adószám alakja nem ismerhető fel",
  "taxid.vatcode": "Az adószám áfakódja érvénytelen",
  "taxid.county": "Az adószám megyekódja érvénytelen",
  "iban.checksum": "A bankszámlaszám ellenőrző összege hibás",
  "format.mismatch": "Formátum nem megfelelő",
  "lines.total_mismatch": "A tételek összege nem egyezik a számla végösszegével",
  "lines.incomplete": "Tételsoron hiányzik az összeg, ezért a tételösszeg nem ellenőrizhető",
  "lines.arithmetic_mismatch": "Tételsoron a mennyiség × egységár vagy a nettó + ÁFA nem adja ki a sor összegét",
});

/** A csomag egy ellenőrzésének eredménye hétköznapi mondatban (a javított, mentett adaton). */
export function checkText(code: string, detail?: string | null): string {
  const known = Object.prototype.hasOwnProperty.call(CHECK_TEXT, code);
  const base = known ? CHECK_TEXT[code] : t("Ellenőrzés nem ment át ({{code}})", { code });
  if (code.startsWith("lines.") && detail) {
    // 053 T3: a tétel-ellenőrzés több sort is nevezhet; a tételösszegnél az eltérés (tételösszeg − végösszeg) oldalanként
    const rows = [...detail.matchAll(/\bline (\d+)\b/g)].map((m) => m[1]);
    const diffs = [...detail.matchAll(/\b(net|gross): sum-total=([-\d.]+)/g)]
      .map((m) => t(m[1] === "net" ? "nettó: eltérés {{diff}}" : "bruttó: eltérés {{diff}}", { diff: num(m[2]) }));
    const extra = [rows.length ? t("{{rows}}. sor", { rows: rows.join("., ") }) : "", ...diffs].filter(Boolean).join("; ");
    return extra ? `${base} (${extra})` : base;
  }
  const row = detail?.match(/\bline (\d+)\b(.*)$/);
  if (row) {
    // a futó egyenlegnél: „expected” = a kivonaton álló egyenleg, „computed” = a nyitó egyenlegből számolt
    const m = row[2].match(/expected ([-\d.]+), computed ([-\d.]+)/);
    return m ? t("{{base}}: {{row}}. sor (a kivonaton {{expected}}, számolva {{computed}})", { base, row: row[1], expected: num(m[1]), computed: num(m[2]) })
      : t("{{base}}: {{row}}. sor", { base, row: row[1] });
  }
  return detail && !known ? `${base}: ${detail}` : base;
}

/** Tizedesjel a választott nyelv szerint (magyarul vessző). */
const num = (s: string | undefined) => (s === undefined ? "" : getLocale() === "hu-HU" ? s.replace(".", ",") : s);

/** Egy teendő-ok kódja hétköznapi mondatban (ismeretlen kódnál maga a kód). */
export function reasonText(code: string): string {
  const p = code.split(":");
  const f = p[2] ? fieldLabel(p[2]) : "";
  const v = num(p[3]);
  switch (`${p[0]}:${p[1] ?? ""}`) {
    case "pick:low_conf": return t("Bizonytalan érték: {{field}} (valószínűség {{p}})", { field: f, p: v });
    case "pick:high_stakes_conf": return t("Kiemelt mező nem elég biztos: {{field}} ({{p}})", { field: f, p: v });
    case "pick:absent_but_chosen": return t("Valószínűleg nincs az iraton, mégis kiválasztódott: {{field}} ({{p}})", { field: f, p: v });
    case "pick:present_but_none": return t("Az iraton van, de nem sikerült kiválasztani: {{field}} ({{p}})", { field: f, p: v });
    case "pick:no_candidates": return t("Nincs jelölt: {{field}}", { field: f });
    case "pick:present_no_candidates": return t("Az iraton van, de a kód nem talált hozzá jelöltet: {{field}} ({{p}})", { field: f, p: v });
    case "pick:none": return t("Nincs érték: {{field}}", { field: f });
    case "jev:unsupported": return t("A modell nem támasztja alá: {{field}}", { field: f });
    case "llm:required_missing": return t("Kötelező mező hiányzik: {{field}}", { field: f });
    case "money:separator_ambiguous": return t("Kétértelmű tizedesjel: {{field}}", { field: f });
    case "ocr:partial_pages": return t("Nem minden oldal lett felismerve ({{pages}})", { pages: p[2] });
    case "ocr:no_text": return t("Az iratból nem sikerült szöveget kinyerni");
    case "ocr:low_confidence": return t("Gyenge szövegfelismerés ({{p}})", { p: num(p[2]) });
    case "ocr:low_conf_words": return t("Sok bizonytalan szó a felismerésben ({{p}})", { p: num(p[2]) });
    case "parties:same_tax_id": return t("A szállító és a vevő adószáma azonos");
    case "parties:same_name": return t("A szállító és a vevő neve azonos");
    case "detect:low_conf": return t("Bizonytalan típusfelismerés: {{type}} ({{p}})", { type: docTypeLabel(p[2]), p: v });
    case "detect:detail_open": return t("A részletes típus nem dönthető el (kategória: {{type}}); válaszd ki kézzel", { type: docTypeLabel(p[2]) });
    case "detect:no_type_pack": return t("Ehhez az irattípushoz nincs adatkinyerés ({{type}}); nézd meg kézzel", { type: docTypeLabel(p[2]) });
    case "detect_detail:low_conf": return t("Bizonytalan részletes típus: {{type}} ({{p}})", { type: docTypeLabel(p[2]), p: v });
    case "detect_detail:second_option": return t("A részletes típusnál a második lehetőség is közel van: {{type}}", { type: docTypeLabel(p[2]) });
    case "intent:low_conf": return t("Bizonytalan levél-szándék: {{intent}} ({{p}})", { intent: intentLabel(p[2]), p: v });
    case "intent:no_result": return t("A levél szándékát nem sikerült felismerni");
  }
  if (p[0] === "validator") return checkText(p[1] ?? "", p.slice(2).join(":") || null);
  if (p[0] === "jev_unavailable") return t("A JEV nem volt elérhető ({{why}}); ellenőrizd kézzel", { why: p.slice(1).join(":") });
  if (p[0] === "llm" && p[1] === "failed") return t("A GPT-kivonat nem sikerült ({{why}})", { why: p[2] ?? "" });
  return code;
}

export function usd(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "–";
  const n = Number(v);
  return Number.isFinite(n) ? `${n.toLocaleString(getLocale(), { minimumFractionDigits: 4, maximumFractionDigits: 6 })} USD` : String(v);
}

/** Költségkeret (058): két tizedes elég (a keret a recept tételenkénti maximumából jön); 1 centnél kisebb érték pontosan. */
export function usdBudget(v: string | number | null | undefined): string {
  const n = Number(v);
  if (v === null || v === undefined || v === "" || !Number.isFinite(n)) return usd(v);
  return n === 0 || Math.abs(n) >= 0.01
    ? `${n.toLocaleString(getLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD` : usd(v);
}

/** A szolgáltató neve a felületen (058: a kulcs helyett). */
export const providerName = (p: string): string => ({ jev: "JEV", openai: "OpenAI", azure_di: "Azure DI" } as Record<string, string>)[p] ?? p;

/** Tétel neve: levélnél a tárgy és a feladó (a szolgáltatás `titles`-a), iratnál a fájlnév (048 T2). */
export const itemName = (i: { item_id: string; source_path: string }, titles?: Record<string, string>) =>
  titles?.[i.item_id] ?? fileName(i.source_path);

export function when(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(getLocale(), { dateStyle: "short", timeStyle: "short" });
}

export const fileName = (p: string) => p.split(/[\\/]/).pop() ?? p;

/** Kereséshez: kisbetű, ékezet nélkül (a szolgáltatás `tablequery.fold` párja) — „szamla” megtalálja a „Számla”-t. */
export const fold = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Szám a választott nyelv írásmódjával (magyarul ezres szóköz, tizedesvessző); nem szám változatlan. */
export function numText(v: unknown, digits = 2): string {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString(getLocale(), { maximumFractionDigits: digits }) : String(v);
}

const STEP_LABEL = tmap({
  empty: "Üres csomag", configure: "Recept kiválasztása", start: "Próbafutás indítása", blocked: "Nem indítható",
  rerun: "Hibás vagy leállított futás: újrafuttatás", done: "Kiadva: eredmény letöltése", approve: "Jóváhagyás",
  go_live: "Próba rendben: éles futás",
});

/** A csomag következő lépése a választott nyelven (057): a szolgáltatás kódjából és paramétereiből; ismeretlen kódnál a
 *  szolgáltatás (magyar) felirata. A csomag fejléce és a munkacsomag-lista oszlopa is ezt használja. */
export function stepLabel(code: string, params: Record<string, unknown> | undefined, fallback: string): string {
  if (code === "running") return t("Fut: {{done}}/{{total}}", { done: params?.done ?? 0, total: params?.total ?? 0 });
  if (code === "review") return t("Ellenőrzés: {{n}} teendő", { n: params?.n ?? 0 });
  return Object.prototype.hasOwnProperty.call(STEP_LABEL, code) ? STEP_LABEL[code] : fallback;
}

/** A futtatás előtti akadály / figyelmeztetés a választott nyelven (a szolgáltatás kódjából; a fájlnév paraméter). */
export function blockerText(b: { code: string; message: string }): string {
  const name = b.message.includes(": ") ? b.message.slice(b.message.indexOf(": ") + 2) : "";
  switch (b.code) {
    case "no_items": return t("A munkacsomagban nincs tétel.");
    case "no_recipe": return t("Nincs hozzárendelt recept.");
    case "recipe_changed": return t("A recept a hozzárendelés óta változott; új hozzárendelés ajánlott.");
    case "unsupported_item": return t("A recept nem kezeli: {{name}}", { name });
    case "source_missing": return t("Hiányzó forrás: {{name}}", { name });
    case "source_changed": return t("A forrás tartalma a felvétel óta változott: {{name}}", { name });
    default: return b.message;
  }
}

/** A csomag tételei szövegesen (058): iratok és levelek külön, hogy a postafiók-csomag ne „irat”-ot mondjon. */
export function itemCountText(items: { kind: string }[]): string {
  const mails = items.filter((i) => i.kind === "email").length;
  const docs = items.length - mails;
  if (mails && docs) return t("{{docs}} irat, {{mails}} levél", { docs, mails });
  return mails ? t("{{n}} levél", { n: mails }) : t("{{n}} irat", { n: docs });
}

// 058: a levél-szándék neve a regiszterből (configs/intents.json), a választott nyelven — kódnév nem jelenik meg
const INTENT: Record<string, string> = tmap(Object.fromEntries(intentRegistry.intents.map((i) => [i.key, i.display_name])));
export const intentLabel = (key: string | null | undefined): string => (key ? INTENT[key] ?? key : "");

/** Recept-paraméterek felirata (058): rövid, kódnév nélküli érték; a hosszú magyarázat a recept szerkesztésében van. */
export const PARAM_LABEL: Record<string, string> = tmap({ arm: "Út", doc_type: "Irattípus", jev_cache: "JEV-válaszok", tasks: "Feladatjavaslat" });
const PARAM_SHORT: Record<string, string> = tmap({
  "arm:auto": "automatikus (az irattípus ajánlása)",
  "arm:S": "kód + JEV",
  "arm:G": "GPT + JEV",
  "jev_cache:reuse": "korábbi válasz újrahasználható",
  "jev_cache:live": "mindig élő hívás",
  "tasks:off": "kikapcsolva",
  "tasks:propose": "bekapcsolva (GPT)",
});
export const paramShort = (k: string, v: string): string => PARAM_SHORT[`${k}:${v}`] ?? (k === "doc_type" ? docTypeLabel(v) : v);
export const paramsText = (params: Record<string, string>): string =>
  Object.entries(params).map(([k, v]) => `${PARAM_LABEL[k] ?? k}: ${paramShort(k, v)}`).join(" · ");

/** 063: egy tétel keretmaximuma szolgáltatónként — a szolgáltatás `work.item_budget` számításának tükre (a recept
 *  adataiból, tétel-fajtánként; a beállítástól függő többlettel, pl. feladatjavaslat a levélen). */
export function itemBudget(r: Recipe, params: Record<string, string>, kind?: string): Record<string, number> {
  const table = (kind && r.max_item_usd_by_kind?.[kind]) || r.max_item_usd;
  const per = table[params.arm ?? "*"] ?? table["*"] ?? {};
  const out: Record<string, number> = Object.fromEntries(Object.entries(per).map(([p, v]) => [p, Number(v)]));
  for (const extra of r.param_item_usd ?? []) {
    if (params[extra.param] === extra.value && (extra.kind === undefined || extra.kind === kind)) {
      for (const [p, v] of Object.entries(extra.usd)) out[p] = (out[p] ?? 0) + Number(v);
    }
  }
  return out;
}

const KIND_BUDGET: Record<string, string> = tmap({ email: "levelenként", document: "PDF-csatolmányonként" });
/** A tételenkénti keret soronként (egy sor tétel-fajtánként), pl. „levelenként: JEV legfeljebb 0,05 USD”. */
export function itemBudgetLines(r: Recipe, params: Record<string, string>): string[] {
  const kinds = r.max_item_usd_by_kind ? Object.keys(r.max_item_usd_by_kind) : [undefined];
  return kinds.map((kind) => {
    const amounts = Object.entries(itemBudget(r, params, kind))
      .map(([p, v]) => t("{{provider}} legfeljebb {{amount}}", { provider: providerName(p), amount: usdBudget(v) })).join(", ") || t("nincs");
    return kind ? `${KIND_BUDGET[kind] ?? kind}: ${amounts}` : t("tételenként: {{amounts}}", { amounts });
  });
}

/** A választható levél-szándékok a regiszter sorrendjében, a választott nyelven (058 K5.1: a szándék kézi javítása). */
export const intentOptions = (): { value: string; label: string }[] =>
  intentRegistry.intents.map((i) => ({ value: i.key, label: t(i.display_name) }));

/** 058 K5.3: a feladatjavaslat akcióinak neve (configs/email_tasks.json), a választott nyelven. */
export const TASK_ACTION: Record<string, string> = tmap(emailTasks.actions as Record<string, string>);
