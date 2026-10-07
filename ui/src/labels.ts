// Labels: statuses, to-do reasons, fields. The codes come from the service; this is display only.
// 057: the label is in the chosen language (i18n `t()`); the Hungarian text is the key. The label maps (`tmap`)
// translate on read, so the call sites need no change; the components update via `useLocale()`.

import fieldLabels from "../../configs/field_labels.json";
import intentRegistry from "../../configs/intents.json";
import emailTasks from "../../configs/email_tasks.json";
import type { Recipe, RunPlan } from "./api";
import { getLocale, t } from "./i18n";

/** A label map that translates on read (`MAP[code]` → in the chosen language). `Object.entries` gives the Hungarian
 *  source. */
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

// 056 U1: the Hungarian names of the fields and the list columns are in configs/field_labels.json — the service reads
// the same file, so service-side search and sorting also go by the Hungarian name. 057: the names of the 23 document
// types are here too.
export const FIELD: Record<string, string> = tmap(fieldLabels.fields);
export const DOC_TYPE: Record<string, string> = tmap(fieldLabels.doc_types);

export const fieldLabel = (f: string) => FIELD[f] ?? f;
export const docTypeLabel = (d: string) => DOC_TYPE[d] ?? d;

/** A column of a line list (and the enumerated values: `column=value`). For an unknown name, the name itself. */
const COLUMN: Record<string, string> = tmap(fieldLabels.columns);
export const columnLabel = (c: string) => COLUMN[c] ?? c.split("=").pop() ?? c;

/** The suggested next step of an email (the service's route code, 048 T2). */
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
/** Intervals in the chosen language (as a function, so that they update on a language switch). */
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
  "iban.hu_account_checksum": "Az IBAN-ban lévő belföldi számlaszám ellenőrző számjegye hibás",
  "account.hu_checksum": "A belföldi bankszámlaszám ellenőrző számjegye hibás",
  "format.mismatch": "Formátum nem megfelelő",
  "lines.total_mismatch": "A tételek összege nem egyezik a számla végösszegével",
  "lines.incomplete": "Tételsoron hiányzik az összeg, ezért a tételösszeg nem ellenőrizhető",
  "lines.arithmetic_mismatch": "Tételsoron a mennyiség × egységár vagy a nettó + ÁFA nem adja ki a sor összegét",
  // 120: the role-pair check (jav/fact_checks.py); written with codepoints for the language guard
  "parties.same_entity": "Ugyanaz a szerepl\u0151 k\u00e9t k\u00fcl\u00f6nb\u00f6z\u0151 szerepben",
  // 121: the pair against the earlier documents of the same type (jav/party_history.py)
  "parties.orientation_reversed": "A k\u00e9t f\u00e9l szerepe ford\u00edtott ahhoz k\u00e9pest, ahogy a kor\u00e1bbi, azonos t\u00edpus\u00fa iratokon \u00e1lltak",
});

/** The result of one of the package's checks as an everyday sentence (on the corrected, saved data). */
export function checkText(code: string, detail?: string | null): string {
  const known = Object.prototype.hasOwnProperty.call(CHECK_TEXT, code);
  const base = known ? CHECK_TEXT[code] : t("Ellenőrzés nem ment át ({{code}})", { code });
  if (code.startsWith("lines.") && detail) {
    // 053 T3: a line-item check may name several rows; for the line-item total, the difference (line-item sum −
    // invoice total) per side
    const rows = [...detail.matchAll(/\bline (\d+)\b/g)].map((m) => m[1]);
    const diffs = [...detail.matchAll(/\b(net|gross): sum-total=([-\d.]+)/g)]
      .map((m) => t(m[1] === "net" ? "nettó: eltérés {{diff}}" : "bruttó: eltérés {{diff}}", { diff: num(m[2]) }));
    const extra = [rows.length ? t("{{rows}}. sor", { rows: rows.join("., ") }) : "", ...diffs].filter(Boolean).join("; ");
    return extra ? `${base} (${extra})` : base;
  }
  const row = detail?.match(/\bline (\d+)\b(.*)$/);
  if (row) {
    // for the running balance: „expected” = the balance printed on the statement, „computed” = the one computed from
    // the opening balance
    const m = row[2].match(/expected ([-\d.]+), computed ([-\d.]+)/);
    return m ? t("{{base}}: {{row}}. sor (a kivonaton {{expected}}, számolva {{computed}})", { base, row: row[1], expected: num(m[1]), computed: num(m[2]) })
      : t("{{base}}: {{row}}. sor", { base, row: row[1] });
  }
  return detail && !known ? `${base}: ${detail}` : base;
}

/** The decimal separator according to the chosen language (a comma in Hungarian). */
const num = (s: string | undefined) => (s === undefined ? "" : getLocale() === "hu-HU" ? s.replace(".", ",") : s);

/** 120: the reading, interpretation and claim states named in native to-dos (codepoints for the language guard). */
const NATIVE_STATUS: Record<string, string> = tmap({
  partial: "r\u00e9szleges",
  resource_limited: "olvas\u00e1si korl\u00e1t",
  unsupported: "nem t\u00e1mogatott",
  corrupt: "s\u00e9r\u00fclt",
  password_required: "jelsz\u00f3val v\u00e9dett",
  excluded: "kiz\u00e1rva",
  temporary_error: "\u00e1tmeneti hiba",
  not_attempted: "nem t\u00f6rt\u00e9nt meg",
  failed: "sikertelen",
  rejected: "elutas\u00edtott v\u00e1lasz",
  uncertain: "bizonytalan",
  missing: "hi\u00e1nyzik",
  conflicting: "ellentmond\u00e1sos",
});
/** A to-do reason code as an everyday sentence (for an unknown code, the code itself). */
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
    case "pick:none_on_cut_list": {
      const [sent, found] = (p[3] ?? "").split("/");
      return t("Nincs érték, pedig a jelöltlista le volt vágva: {{field}} ({{found}} jelöltből {{sent}} ment a modellnek)", { field: f, sent, found });
    }
    case "jev:unsupported": return t("A modell nem támasztja alá: {{field}}", { field: f });
    // 085: processing without JEV: the extracted value is printed nowhere on the document (the code's own check)
    case "source:not_found": return t("A kinyert érték nem szerepel az iratban: {{field}}", { field: f });
    // 092: without JEV, an accounting field GPT is not sure enough of (below the policy's review_below)
    case "gpt:low_conf": return t("A GPT nem elég biztos az értékben: {{field}} (valószínűség {{p}})", { field: f, p: v });
    case "llm:required_missing": return t("Kötelező mező hiányzik: {{field}}", { field: f });
    case "money:separator_ambiguous": return t("Kétértelmű tizedesjel: {{field}}", { field: f });
    // 081: the S path's safety net: the picked number stands on the page only as a piece of a longer number
    case "money:token_cut": return t("A kiválasztott érték csak egy része az iraton nyomtatott számnak: {{field}}", { field: f });
    // 084: the shared date reader: the printed date's day and month can be read two ways ("04/12/2022")
    case "date:order_ambiguous": return t("A nap és a hónap sorrendje kétes: {{field}}", { field: f });
    case "ocr:partial_pages": return t("Nem minden oldal lett felismerve ({{pages}})", { pages: p[2] });
    case "ocr:no_text": return t("Az iratból nem sikerült szöveget kinyerni");
    case "ocr:low_confidence": return t("Gyenge szövegfelismerés ({{p}})", { p: num(p[2]) });
    case "ocr:low_conf_words": return t("Sok bizonytalan szó a felismerésben ({{p}})", { p: num(p[2]) });
    // 075: the Azure escalation of a weak scan did not run (jav/ocr.py escalation_review_reasons); 121: no route, failed call
    case "ocr:escalation_blocked":
      if (p[2] === "uncertain_attempt") return t("Gyenge helyi felismerés; egy korábbi Azure-hívás kimenete bizonytalan, ezért nem ismételtük meg");
      if (p[2] === "unreachable") return t("Weak local recognition; Azure recognition is not set up for this document");
      if (p[2] === "unavailable") return t("Weak local recognition; Azure recognition failed");
      return t("Gyenge helyi felismerés; az Azure-felismerés a futás kerete miatt elmaradt");
    // 078: a PDF attachment the reader could not read; the email's intent was still recognised
    case "attachment:unreadable": return t("Egy PDF-csatolmány nem olvasható (sérült, túl nagy, vagy túllépte az olvasási időt vagy memóriát); a levél szándéka ettől még elkészült");
    // 126: a suspected duplicate invoice (jav/duplicates.py); decided in its own panel on the review page
    case "duplicate:copy": return t("Possible copy of an earlier document (same invoice number and supplier)");
    case "duplicate:variant": return t("Possible modified version of an earlier document (same invoice number and supplier, different values)");
    case "duplicate:undecidable": return t("Possible duplicate of an earlier document (same invoice number and supplier, a value is missing)");
    case "parties:same_tax_id": return t("A szállító és a vevő adószáma azonos");
    case "parties:same_name": return t("A szállító és a vevő neve azonos");
    case "detect:low_conf": return t("Bizonytalan típusfelismerés: {{type}} ({{p}})", { type: docTypeLabel(p[2]), p: v });
    case "detect:detail_open": return t("A részletes típus nem dönthető el (kategória: {{type}}); válaszd ki kézzel", { type: docTypeLabel(p[2]) });
    case "detect:no_type_pack": return t("Ehhez az irattípushoz nincs adatkinyerés ({{type}}); nézd meg kézzel", { type: docTypeLabel(p[2]) });
    // 090: the type / issuer cross-check in code (configs/policy.json detect_issuer): the type is kept
    case "detect:issuer_mismatch": return t("A típus ({{type}}) magyar kiállítót feltételez, de a felismerés szerint a kiállító nem magyar; ellenőrizd a típust", { type: docTypeLabel(p[2]) });
    case "detect_detail:low_conf": return t("Bizonytalan részletes típus: {{type}} ({{p}})", { type: docTypeLabel(p[2]), p: v });
    case "detect_detail:second_option": return t("A részletes típusnál a második lehetőség is közel van: {{type}}", { type: docTypeLabel(p[2]) });
    // 086: type recognition by GPT (processing without JEV)
    case "detect:gpt_failed": return t("A GPT-s típusfelismerés nem sikerült ({{why}}); válaszd ki kézzel", { why: p[2] ?? "" });
    case "detect:confidence_unavailable": return t("A típusfelismerés bizonyossága nem mérhető: {{type}}; ellenőrizd kézzel", { type: docTypeLabel(p[2]) });
    case "detect_detail:gpt_failed": return t("A részletes típus GPT-s felismerése nem sikerült ({{why}}); válaszd ki kézzel", { why: p[2] ?? "" });
    case "detect_detail:confidence_unavailable": return t("A részletes típus bizonyossága nem mérhető: {{type}}; ellenőrizd kézzel", { type: docTypeLabel(p[2]) });
    case "intent:low_conf": return t("Bizonytalan levél-szándék: {{intent}} ({{p}})", { intent: intentLabel(p[2]), p: v });
    case "intent:no_result": return t("A levél szándékát nem sikerült felismerni");
    // 089: the intent recognised by GPT (processing without JEV)
    case "intent:gpt_failed": return t("A GPT-s szándékfelismerés nem sikerült ({{why}}); olvasd el a levelet, és döntsd el kézzel", { why: p[2] ?? "" });
    case "intent:confidence_unavailable": return t("A levél-szándék bizonyossága nem mérhető; ellenőrizd kézzel");
    // 086: processing without JEV, before 089 (older runs): the intent was not recognised at all
    case "intent:jev_off": return t("JEV nélküli feldolgozás: a levél szándékát a rendszer nem ismeri fel; olvasd el, és döntsd el kézzel");
    // 073: task proposals from an e-mail (jav/flow_email.py); until now these showed the raw code
    case "tasks:proposed": return t("{{n}} feladatjavaslat vár döntésre", { n: p[2] ?? "" });
    case "tasks:failed": return t("A feladatjavaslat nem sikerült ({{why}})", { why: p[2] ?? "" });
    // 120: the to-dos of Word, Excel, text and continuing PDF documents (jav/flow_native.py)
    case "native:reading": return t("Az irat nem teljesen olvashat\u00f3 ({{status}}); n\u00e9zd meg a forr\u00e1st \u00e9s a hi\u00e1nyokat", { status: NATIVE_STATUS[p[2]] ?? p[2] ?? "" });
    case "native:interpretation": return t("Az adatkinyer\u00e9s nem siker\u00fclt ({{status}}); n\u00e9zd meg az ok\u00e1t", { status: NATIVE_STATUS[p[2]] ?? p[2] ?? "" });
    case "native:no_facts": return t("Az iratb\u00f3l nem keletkezett adatjavaslat");
    case "native:interpretation_gaps": return t("Az adatkinyer\u00e9s hi\u00e1nyt jelzett");
    // 124: a scan read from its Azure recognition (weak word confidences), or the native step's own Azure call
    // did not run (jav/flow_native.py review_native)
    case "native:recognition":
      if (p[2] === "low_confidence") return t("Weak Azure recognition ({{p}})", { p: num(p[3]) });
      if (p[2] === "low_conf_words") return t("Many uncertain words in the Azure recognition ({{p}})", { p: num(p[3]) });
      if (p[3] === "uncertain_attempt") return t("An earlier Azure call has an uncertain outcome, so it was not repeated; local recognition was used");
      if (p[3] === "unreachable") return t("Azure recognition is not set up for this document; local recognition was used");
      if (p[3] === "unavailable") return t("Azure recognition failed; local recognition was used");
      return t("Azure recognition was skipped because of the run's budget; local recognition was used");
    // 123: facts left out of a received answer for breaking the presence rule
    case "native:discarded_facts": return t("{{n}} adatjavaslat hib\u00e1s szerkezet\u0171 volt, ez\u00e9rt kimaradt; n\u00e9zd meg a forr\u00e1st", { n: p[2] ?? "" });
    case "native:grounding": return t("Egy adatjavaslat nem tal\u00e1lhat\u00f3 sz\u00f3 szerint a forr\u00e1sban");
    case "native:claim": return t("Egy adatjavaslat nem biztos ({{state}})", { state: NATIVE_STATUS[p[2]] ?? p[2] ?? "" });
    case "native:fact": {
      const n = Number(p[2]) + 1;
      if (p[3] === "unsupported") return t("A JEV nem t\u00e1masztja al\u00e1 a(z) {{n}}. adatjavaslatot ({{p}})", { n, p: num(p[4]) });
      if (p[3] === "uncertain") return t("A JEV bizonytalan a(z) {{n}}. adatjavaslatban ({{p}})", { n, p: num(p[4]) });
      return t("A(z) {{n}}. adatjavaslathoz figyelmeztet\u00e9s tartozik; ellen\u0151rizd", { n });
    }
  }
  // 090: a field check's to-do names its field third (`validator:taxid.unrecognized:supplier_tax_id`)
  if (p[0] === "validator" && p.length === 3 && FIELD[p[2]]) return `${checkText(p[1] ?? "")}: ${fieldLabel(p[2])}`;
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

/** Cost budget (058): two decimals are enough (the budget comes from the recipe's per-item maximum); a value below
 *  1 cent is shown exactly. */
export function usdBudget(v: string | number | null | undefined): string {
  const n = Number(v);
  if (v === null || v === undefined || v === "" || !Number.isFinite(n)) return usd(v);
  return n === 0 || Math.abs(n) >= 0.01
    ? `${n.toLocaleString(getLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD` : usd(v);
}

/** The provider's name in the interface (058: instead of the key). */
export const providerName = (p: string): string => ({ jev: "JEV", openai: "OpenAI", azure_di: "Azure DI" } as Record<string, string>)[p] ?? p;

/** An item's name: for an email, the subject and the sender (the service's `titles`); for a document, the file name
 *  (048 T2). */
export const itemName = (i: { item_id: string; source_path: string }, titles?: Record<string, string>) =>
  titles?.[i.item_id] ?? fileName(i.source_path);

export function when(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(getLocale(), { dateStyle: "short", timeStyle: "short" });
}

export const fileName = (p: string) => p.split(/[\\/]/).pop() ?? p;

/** For search: lower case, without accents (the counterpart of the service's `tablequery.fold`) — „szamla” finds
 *  „Számla”. */
export const fold = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** A number in the chosen language's notation (in Hungarian: a space between thousands and a decimal comma); a
 *  non-number stays unchanged. */
export function numText(v: unknown, digits = 2): string {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString(getLocale(), { maximumFractionDigits: digits }) : String(v);
}

/** 081: a stored amount or quantity ("35.56", "28000") in the editing form, the Hungarian way: a decimal comma and no
 *  grouping ("35,56"). The local service reads what is typed back by the same habit ("28.000" = 28 000). */
export function editNumber(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  return String(v).replace(".", ",");
}

/** 081: the saved amounts and quantities, read back for the save message („Nettó összeg: 28 000”); 084: the saved
 *  dates too, as the service read them („Kiállítás dátuma: 2022-12-04”). */
export function savedValues(fields: Record<string, unknown>, kinds: Record<string, string>): string {
  return Object.entries(fields)
    .filter(([f, v]) => ["money", "number", "date"].includes(kinds[f]) && v !== null && v !== undefined && !Array.isArray(v))
    .map(([f, v]) => `${fieldLabel(f)}: ${kinds[f] === "date" ? String(v) : numText(v, 6)}`)
    .join("; ");
}

const STEP_LABEL = tmap({
  empty: "Üres csomag", start: "Próbafutás indítása", blocked: "Nem indítható",
  rerun: "Hibás vagy leállított futás: újrafuttatás", done: "Kiadva: eredmény letöltése", approve: "Jóváhagyás",
  go_live: "Próba rendben: éles futás",
});

/** The package's next step in the chosen language (057): from the service's code and parameters; for an unknown code,
 *  the service's (Hungarian) label. Both the package header and the work package list column use it. */
export function stepLabel(code: string, params: Record<string, unknown> | undefined, fallback: string): string {
  if (code === "running") return t("Fut: {{done}}/{{total}}", { done: params?.done ?? 0, total: params?.total ?? 0 });
  if (code === "review") return t("Ellenőrzés: {{n}} teendő", { n: params?.n ?? 0 });
  return Object.prototype.hasOwnProperty.call(STEP_LABEL, code) ? STEP_LABEL[code] : fallback;
}

/** A pre-run blocker / warning in the chosen language (from the service's code; the file name is a parameter). */
export function blockerText(b: { code: string; message: string }): string {
  const name = b.message.includes(": ") ? b.message.slice(b.message.indexOf(": ") + 2) : "";
  switch (b.code) {
    case "no_items": return t("A munkacsomagban nincs tétel.");
    // 080: the processing settings replace the recipe; a package without settings runs with the default ones
    case "recipe_changed": return t("A feldolgozás a beállítások mentése óta változott; mentsd el újra a beállításokat.");
    case "recipe_retired": return t("A csomag egy megszűnt feldolgozási változatot használ; állítsd át a mostani feldolgozásra.");
    case "unsupported_item": return t("A feldolgozás nem kezeli: {{name}}", { name });
    case "source_missing": return t("Hiányzó forrás: {{name}}", { name });
    case "source_changed": return t("A forrás tartalma a felvétel óta változott: {{name}}", { name });
    case "instance_damaged": return t("A felvételkori példány hiányzik vagy sérült: {{name}}", { name });
    case "original_changed": return t("Az eredeti fájl a felvétel óta megváltozott; a felvételkori példány kerül feldolgozásra: {{name}}", { name });
    case "original_missing": return t("Az eredeti fájl a felvétel óta eltűnt; a felvételkori példány kerül feldolgozásra: {{name}}", { name });
    default: return b.message;
  }
}

/** The package's items as text (058): documents and emails separately, so that a mailbox package does not say
 *  „irat” (document). */
export function itemCountText(items: { kind: string }[]): string {
  const mails = items.filter((i) => i.kind === "email").length;
  const docs = items.length - mails;
  if (mails && docs) return t("{{docs}} irat, {{mails}} levél", { docs, mails });
  return mails ? t("{{n}} levél", { n: mails }) : t("{{n}} irat", { n: docs });
}

// 058: the email intent's name from the registry (configs/intents.json), in the chosen language — no code name is shown
const INTENT: Record<string, string> = tmap(Object.fromEntries(intentRegistry.intents.map((i) => [i.key, i.display_name])));
export const intentLabel = (key: string | null | undefined): string => (key ? INTENT[key] ?? key : "");

/** Labels of the processing settings (058; 080: the path by what it does, the owner's decision of 2026-10-01): a short
 *  value without code names; the long explanation is in the settings editor and on Settings › Processing. */
export const PARAM_LABEL: Record<string, string> = tmap({ path: "Feldolgozási út", arm: "Út", doc_type: "Irattípus", jev_cache: "Korábbi válaszok", tasks: "Feladatjavaslat", azure_ocr: "Azure-felismerés", jev: "JEV használata",
  unknown_documents: "Ismeretlen PDF-ek" });  // 120
const PARAM_SHORT: Record<string, string> = tmap({
  "jev:on": "bekapcsolva",
  "jev:off": "kikapcsolva — csak GPT (OpenAI)",
  // 090: the path and the use of JEV as one choice (`path`, shown only)
  "path:auto": "Automatikus (ajánlott) — JEV és GPT",
  "path:S": "JEV, ahol lehet — olcsóbb, tételsorok nélkül; máshol GPT (S)",
  "path:G": "GPT + JEV — tételsorokkal (G)",
  "path:gpt": "Csak GPT, JEV nélkül (OpenAI)",
  "path:jev": "JEV-vel (ajánlott)",
  "arm:auto": "Automatikus (ajánlott)",
  "arm:S": "JEV, ahol lehet — olcsóbb, tételsorok nélkül; máshol GPT (S)",
  "arm:G": "GPT + JEV — tételsorokkal (G)",
  "jev_cache:reuse": "korábbi válasz újrahasználható",
  "jev_cache:live": "mindig élő hívás",
  "tasks:off": "kikapcsolva",
  "tasks:propose": "bekapcsolva (GPT)",
  "azure_ocr:on": "gyenge szkennelésnél",
  "azure_ocr:off": "kikapcsolva",
  // 120: a text PDF without a fitting type pack (written with codepoints for the language guard)
  "unknown_documents:facts": "\u00e1ltal\u00e1nos adatjavaslat (GPT + JEV)",
  "unknown_documents:review": "meg\u00e1ll, k\u00e9zi ellen\u0151rz\u00e9s",
});
/** 080: the item kind a setting acts on (the path, Azure and the document type on documents, task proposals on
 *  emails); a setting not listed acts on every item. With the package's item kinds known, a setting that cannot act on
 *  any of them is not shown. */
const PARAM_KIND: Record<string, string> = { arm: "document", azure_ocr: "document", doc_type: "document", tasks: "email",
  unknown_documents: "document" };
export const paramApplies = (k: string, kinds?: string[]): boolean => !kinds?.length || !PARAM_KIND[k] || kinds.includes(PARAM_KIND[k]);
/** 089 (the owner's decision of 2026-10-02): a setting that only counts while another setting has a given value.
 *  Without JEV (086) every document runs on the G path, so the documents' path does not count. A missing value counts
 *  as the needed one: an assignment from before the switch ran with JEV. 090: the earlier answers (`jev_cache`) count
 *  for GPT too, so they are shown on every path. */
const PARAM_NEEDS: Record<string, [string, string]> = { arm: ["jev", "on"] };
export const paramInEffect = (k: string, params: Record<string, string>): boolean => {
  const need = PARAM_NEEDS[k];
  return !need || (params[need[0]] ?? need[1]) === need[1];
};

/** 090 (the owner's trial and decision of 2026-10-02, "one picker, four paths"): the documents' path and the use of
 *  JEV are one choice on screen, the processing path (`path`): automatic, JEV where possible (S), GPT + JEV (G), or
 *  GPT only, without JEV. The saved settings keep their two values (`arm`, `jev`), so packages, runs and measurements
 *  stay as they are. The documents' path does not act on emails, so a package of emails only chooses between "with
 *  JEV" (`jev`) and "GPT only" (`gpt`). Unknown item kinds count as documents. */
export const PATH = "path";
const withDocuments = (kinds?: string[]) => !kinds?.length || kinds.includes("document");
const hasPath = (keys: string[]) => keys.includes("arm") && keys.includes("jev");
export function pathValue(params: Record<string, string>, kinds?: string[]): string {
  if ((params.jev ?? "on") === "off") return "gpt";
  return withDocuments(kinds) ? params.arm ?? "auto" : "jev";
}
export const pathOptions = (armAllowed: string[], kinds?: string[]): string[] =>
  withDocuments(kinds) ? [...armAllowed, "gpt"] : ["jev", "gpt"];
export function applyPath(params: Record<string, string>, path: string): Record<string, string> {
  if (path === "gpt") return { ...params, jev: "off" };
  return path === "jev" ? { ...params, jev: "on" } : { ...params, jev: "on", arm: path };
}
/** The settings shown, in order: the processing path first (for a recipe with both values), then the recipe's other
 *  settings that count and act on the package's items. */
export function shownParams(keys: string[], params: Record<string, string>, kinds?: string[]): string[] {
  const merged = hasPath(keys);
  const rest = keys.filter((k) => !(merged && (k === "arm" || k === "jev")) && paramApplies(k, kinds) && paramInEffect(k, params));
  return merged ? [PATH, ...rest] : rest;
}
/** A shown setting's value: the processing path from the two saved values, any other setting as saved. */
export const shownValue = (k: string, params: Record<string, string>, kinds?: string[]): string =>
  k === PATH ? pathValue(params, kinds) : params[k] ?? "";
export const paramShort = (k: string, v: string): string => PARAM_SHORT[`${k}:${v}`] ?? (k === "doc_type" ? docTypeLabel(v) : v);
export const paramsText = (params: Record<string, string>): string =>
  shownParams(Object.keys(params), params).map((k) => `${PARAM_LABEL[k] ?? k}: ${paramShort(k, shownValue(k, params))}`).join(" · ");

/** 063: an item's budget maximum per provider — a mirror of the service's `work.item_budget` calculation (from the
 *  recipe's data, per item kind; with the setting-dependent extra, e.g. task proposals on an email). */
export function itemBudget(r: Recipe, params: Record<string, string>, kind?: string): Record<string, number> {
  const table = (kind && r.max_item_usd_by_kind?.[kind]) || r.max_item_usd;
  const per = table[params.arm ?? "*"] ?? table["*"] ?? {};
  const out: Record<string, number> = Object.fromEntries(Object.entries(per).map(([p, v]) => [p, Number(v)]));
  const drop = new Set<string>();
  for (const extra of r.param_item_usd ?? []) {
    // 075: a parameter missing from an older assignment counts with the recipe's default (as on the service)
    if ((params[extra.param] ?? r.params[extra.param]?.default) === extra.value && (extra.kind === undefined || extra.kind === kind)) {
      for (const [p, v] of Object.entries(extra.usd)) out[p] = (out[p] ?? 0) + Number(v);
      for (const p of extra.drop ?? []) drop.add(p); // 086: e.g. without JEV the item has no JEV budget at all
    }
  }
  return Object.fromEntries(Object.entries(out).filter(([p]) => !drop.has(p)));
}

const KIND_BUDGET: Record<string, string> = tmap({ email: "levelenként", document: "PDF-iratonként" });
/** The per-item budget line by line (one line per item kind), e.g. „levelenként: JEV legfeljebb 0,05 USD” (per email:
 *  JEV at most 0.05 USD). */
export function itemBudgetLines(r: Recipe, params: Record<string, string>, only?: string[]): string[] {
  // 080: `only` — the package's item kinds; the other kinds' lines are left out
  const kinds = (r.max_item_usd_by_kind ? Object.keys(r.max_item_usd_by_kind) : [undefined])
    .filter((kind) => !kind || !only?.length || only.includes(kind));
  return kinds.map((kind) => {
    const amounts = Object.entries(itemBudget(r, params, kind))
      .map(([p, v]) => t("{{provider}} legfeljebb {{amount}}", { provider: providerName(p), amount: usdBudget(v) })).join(", ") || t("nincs");
    return kind ? `${KIND_BUDGET[kind] ?? kind}: ${amounts}` : t("tételenként: {{amounts}}", { amounts });
  });
}

/** 080 (the pre-start overview, F-külső-kapcsolók): what a run will do, one line per service — the budget maximum and
 *  what it is for, from the readiness check's `plan` and `budget`. A service with no budget is said not to be called. */
export function planLines(plan: RunPlan, budget: Record<string, string>): string[] {
  const amount = (p: string) => Number(budget[p] ?? 0);
  const head = (p: string) => t("{{provider}} legfeljebb {{amount}}", { provider: providerName(p), amount: usdBudget(budget[p]) });
  const join = (parts: (string | false)[]) => parts.filter(Boolean).join("; ");
  const out: string[] = [];
  if (plan.documents) out.push(t("Helyi szövegfelismerés: ingyenes, minden iraton."));
  if (amount("jev") > 0) {
    out.push(`${head("jev")}: ${join([
      plan.documents > 0 && t("{{n}} irat típusfelismerése és adatkinyerése", { n: plan.documents }),
      plan.emails > 0 && t("{{n}} levél szándékfelismerése", { n: plan.emails }),
      plan.jev_reuse ? t("a korábban már feltett kérdésekért nem kell újra fizetni") : t("minden kérdés élő hívás, a korábbi válaszok nem számítanak"),
    ])}.`);
  }
  if (plan.jev === false) {
    // 086: processing without JEV — no JEV budget, so not even a stray JEV call could start
    out.push(t("JEV: nem hívódik (kikapcsolva)."));
  }
  if (amount("openai") > 0 && plan.jev === false) {
    out.push(`${head("openai")}: ${join([
      plan.documents > 0 && t("{{n}} irat típusfelismerése és adatkinyerése a G-úton, kódos ellenőrzéssel", { n: plan.documents }),
      plan.emails > 0 && t("{{n}} levél szándékfelismerése", { n: plan.emails }),  // 089: by GPT without JEV
      plan.tasks_emails > 0 && t("{{n}} levél feladatjavaslata", { n: plan.tasks_emails }),
    ])}.`);
  } else if (amount("openai") > 0) {
    out.push(`${head("openai")}: ${join([
      plan.paths.G > 0 && (plan.arm === "S"  // 082: the S path runs on G where the type has no JEV path
        ? t("{{n}} irat a G-úton, mert a típusának nincs JEV-útja", { n: plan.paths.G })
        : t("{{n}} irat a G-úton", { n: plan.paths.G })),
      plan.paths.unknown > 0 && t("{{n}} még ismeretlen típusú irat, ha a felismert típus a G-utat kéri", { n: plan.paths.unknown }),
      plan.tasks_emails > 0 && t("{{n}} levél feladatjavaslata", { n: plan.tasks_emails }),
    ])}.`);
  } else if (plan.documents || plan.emails) {
    out.push(plan.documents ? t("OpenAI: nem hívódik, minden irat az S-úton fut.") : t("OpenAI: nem hívódik."));
  }
  if (amount("azure_di") > 0) out.push(`${head("azure_di")}: ${t("csak gyenge minőségű szkennelésnél, a helyi felismerés helyett")}.`);
  else if (plan.documents) out.push(t("Azure DI: nem hívódik (kikapcsolva)."));
  return out;
}

/** The selectable email intents in registry order, in the chosen language (058 K5.1: correcting the intent by hand). */
export const intentOptions = (): { value: string; label: string }[] =>
  intentRegistry.intents.map((i) => ({ value: i.key, label: t(i.display_name) }));

/** 058 K5.3: the names of the task proposal actions (configs/email_tasks.json), in the chosen language. */
export const TASK_ACTION: Record<string, string> = tmap(emailTasks.actions as Record<string, string>);
