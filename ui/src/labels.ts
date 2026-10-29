// Labels: statuses, to-do reasons, fields. The codes come from the service; this is display only.
// 057: the label is in the chosen language (i18n `t()`); the Hungarian text is the key. The label maps (`tmap`)
// translate on read, so the call sites need no change; the components update via `useLocale()`.

import fieldLabels from "../../configs/field_labels.json";
import intentRegistry from "../../configs/intents.json";
import emailTasks from "../../configs/email_tasks.json";
import type { Recipe, RunPlan, Said } from "./api";
import { getLocale, t } from "./i18n";

/** A label map that translates on read (`MAP[code]` → in the chosen language). `Object.entries` gives the Hungarian
 *  source. */
export function tmap(source: Record<string, string>): Record<string, string> {
  return new Proxy(source, { get: (o, k) => (typeof k === "string" && typeof o[k] === "string" ? t(o[k]) : Reflect.get(o, k)) });
}

/** 160-D: the AI engine's short name (Settings › Processing, the workflow wizard and its control view). */
export const ENGINE: Record<string, string> = tmap({ jev: "JEV and GPT", gpt: "GPT only" });

export const RUN_STATUS: Record<string, string> = tmap({
  queued: "Waiting in the queue",
  running: "Running",
  needs_review: "To-dos pending",
  done: "Done",
  failed: "Faulty",
  cancelled: "Stopped",
});

export const ITEM_STATUS: Record<string, string> = tmap({
  done: "Processed",
  failed: "Faulty",
  cancelled: "Stopped",
  needs_review: "To-do",
  needs_ocr: "OCR needed",
});

export const FINAL_STATUS: Record<string, string> = tmap({
  done: "Closed, no to-dos",
  needs_review: "To-do",
  needs_ocr: "OCR needed",
  jev_unavailable: "JEV was unavailable",
});

export const MODE: Record<string, string> = tmap({ shadow: "Trial", apply: "Live" });

// 056 U1: the Hungarian names of the fields and the list columns are in configs/field_labels.json — the service reads
// the same file, so service-side search and sorting also go by the Hungarian name. 057: the names of the 23 document
// types are here too.
export const FIELD: Record<string, string> = tmap(fieldLabels.fields);
export const DOC_TYPE: Record<string, string> = tmap(fieldLabels.doc_types);
// 261: a download's mailbox label is the email domain's (`ui/src/domains/email/labels.ts`)

/** 197: a type's own name for a shared field (the quote request's customer is the requester). */
const BY_TYPE = fieldLabels.by_type as Record<string, Record<string, string> | undefined>;
/** A field's name; with the document's type, that type's own name when it has one. */
export const fieldLabel = (f: string, docType?: string | null) => {
  const own = docType ? BY_TYPE[docType]?.[f] : undefined;
  return own ? t(own) : FIELD[f] ?? f;
};
export const docTypeLabel = (d: string) => DOC_TYPE[d] ?? d;

/** A column of a line list (and the enumerated values: `column=value`). For an unknown name, the name itself. */
const COLUMN: Record<string, string> = tmap(fieldLabels.columns);
export const columnLabel = (c: string) => COLUMN[c] ?? c.split("=").pop() ?? c;

/** The suggested next step of an email (the service's route code, 048 T2). 192 (backlog Q-m2-label-text): `readsText`
 *  (the service's `next_flow_reads_text`): the type reads the email's own text too, so the step names the email. */
export function nextFlowText(code: string | null | undefined, readsText = false): string {
  if (!code) return "–";
  const [kind, what] = code.split(":");
  if (kind === "m2" && what !== "needs_ocr" && readsText) {
    return t("Data extraction from the email and its attachments ({{what}})", { what: docTypeLabel(what) });
  }
  if (kind === "m2") return what === "needs_ocr" ? t("Attachment: OCR needed") : t("Data extraction from the attachment ({{what}})", { what: docTypeLabel(what) });
  if (kind === "m1") return t("Attachment: type recognition");
  const archive = tmap({ payment_proof: "payment proof", calendar: "calendar", order_status: "order status",
    sent: "sent message" });
  if (kind === "archive") return what ? t("Archive ({{what}})", { what: archive[what] ?? what }) : t("Archive");
  const human = tmap({ inbox: "Manual processing", fetch_document: "Manual: process the invoice",
    low_confidence: "Manual review: uncertain intent", jev_unavailable: "Manual review: JEV was unavailable",
    suspicious: "Manual review: suspicious content" });
  if (kind === "human") return human[what] ?? t("Manual processing");
  return code;
}

const INTERVAL_NAMES = tmap({ "15": "every 15 minutes", "30": "every 30 minutes", "60": "hourly", "240": "every 4 hours", "1440": "daily" });
/** Intervals in the chosen language (as a function, so that they update on a language switch). */
export const intervals = (): [number, string][] => [15, 30, 60, 240, 1440].map((m) => [m, INTERVAL_NAMES[String(m)]]);
export const intervalText = (min: number) => intervals().find(([m]) => m === min)?.[1] ?? t("every {{min}} minutes", { min });

const CHECK_TEXT: Record<string, string> = tmap({
  "balance.discontinuity": "The running balance is broken",
  "balance.opening_unparseable": "The opening balance cannot be parsed",
  "balance.amount_unparseable": "A transaction amount cannot be parsed",
  "balance.running_unparseable": "A transaction balance cannot be parsed",
  "closing.mismatch": "Opening balance + transactions do not add up to the closing balance",
  "closing.unparseable": "The opening or closing balance is missing / cannot be parsed",
  "closing.amount_unparseable": "A transaction amount cannot be parsed",
  "closing.from_lines": "The balances were taken from the lines themselves (no total row)",  // 174 (review 160 M-12)
  "totals.mismatch": "The total debits / credits do not match the transactions",
  "totals.amount_unparseable": "A transaction amount cannot be parsed",
  "totals.unparseable": "The net, VAT or gross amount is missing",
  "dates.out_of_period": "Transaction outside the statement period",
  "dates.due_before_issue": "The payment due date is before the issue date",
  "dates.unparseable": "The dates cannot be parsed",
  "taxid.checkdigit": "The tax ID check digit is wrong",
  "taxid.unrecognized": "The tax ID format is not recognised",
  "taxid.vatcode": "The tax ID VAT code is invalid",
  "taxid.county": "The tax ID county code is invalid",
  "iban.checksum": "The bank account number checksum is wrong",
  "iban.hu_account_checksum": "The check digit of the domestic account number inside the IBAN is wrong",
  "account.hu_checksum": "The check digit of the domestic bank account number is wrong",
  "format.mismatch": "Invalid format",
  "lines.total_mismatch": "The sum of the line items does not match the invoice total",
  "lines.incomplete": "A line item has no amount, so the line total cannot be checked",
  "lines.arithmetic_mismatch": "On a line item, quantity × unit price or net + VAT does not equal the line amount",
  // 190: the checks of any list field by its name (jav/ai/validators.py list_rows, list_values, list_positive)
  "lines.too_few": "A list has fewer rows than it should (for example, no requested item at all)",
  "lines.value_missing": "A list row lacks a value it needs",
  "lines.not_positive": "A quantity in a list row is zero or less",
  // 120: the role-pair check (jav/documents/fact_checks.py); written with codepoints for the language guard
  "parties.same_entity": "The same party appears in two different roles",
  // 121: the pair against the earlier documents of the same type (jav/ai/party_history.py)
  "parties.orientation_reversed": "The two parties stand the other way round than on their earlier documents of the same type",
});

/** The result of one of the package's checks as an everyday sentence (on the corrected, saved data). */
export function checkText(code: string, detail?: string | null): string {
  // 153 (review): an invoice's VAT check shares its code with a statement's totals check; its detail tells them apart
  if (code === "totals.mismatch" && detail?.startsWith("net+vat-gross=")) {
    const diff = detail.match(/^net\+vat-gross=([-\d.]+)/)?.[1];
    const base = t("The net amount and the VAT do not add up to the gross amount");
    return diff ? `${base} (${t("difference: {{diff}}", { diff: num(diff) })})` : base;
  }
  const known = Object.prototype.hasOwnProperty.call(CHECK_TEXT, code);
  const base = known ? CHECK_TEXT[code] : t("Check failed ({{code}})", { code });
  if (code.startsWith("lines.") && detail) {
    // 053 T3: a line-item check may name several rows; for the line-item total, the difference (line-item sum −
    // invoice total) per side
    // 190: a row named twice (two of its values) is listed once
    const rows = [...new Set([...detail.matchAll(/\bline (\d+)\b/g)].map((m) => m[1]))];
    const diffs = [...detail.matchAll(/\b(net|gross): sum-total=([-\d.]+)/g)]
      .map((m) => t(m[1] === "net" ? "net: difference {{diff}}" : "gross: difference {{diff}}", { diff: num(m[2]) }));
    const extra = [rows.length ? t("row {{rows}}", { rows: rows.join("., ") }) : "", ...diffs].filter(Boolean).join("; ");
    return extra ? `${base} (${extra})` : base;
  }
  const row = detail?.match(/\bline (\d+)\b(.*)$/);
  if (row) {
    // for the running balance: „expected” = the balance printed on the statement, „computed” = the one computed from
    // the opening balance
    const m = row[2].match(/expected ([-\d.]+), computed ([-\d.]+)/);
    return m ? t("{{base}}: row {{row}} (on the statement {{expected}}, computed {{computed}})", { base, row: row[1], expected: num(m[1]), computed: num(m[2]) })
      : t("{{base}}: row {{row}}", { base, row: row[1] });
  }
  return detail && !known ? `${base}: ${detail}` : base;
}

/** The decimal separator according to the chosen language (a comma in Hungarian). */
const num = (s: string | undefined) => (s === undefined ? "" : getLocale() === "hu-HU" ? s.replace(".", ",") : s);

/** 120: the reading, interpretation and claim states named in native to-dos (codepoints for the language guard). */
const NATIVE_STATUS: Record<string, string> = tmap({
  partial: "partial",
  resource_limited: "reading limit",
  unsupported: "unsupported",
  corrupt: "damaged",
  password_required: "password-protected",
  excluded: "excluded",
  temporary_error: "temporary error",
  not_attempted: "not attempted",
  failed: "failed",
  rejected: "rejected answer",
  uncertain: "uncertain",
  missing: "missing",
  conflicting: "conflicting",
});
/** A to-do reason code as an everyday sentence (for an unknown code, the code itself). */
export function reasonText(code: string): string {
  const p = code.split(":");
  const f = p[2] ? fieldLabel(p[2]) : "";
  const v = num(p[3]);
  switch (`${p[0]}:${p[1] ?? ""}`) {
    case "pick:low_conf": return t("Uncertain value: {{field}} (probability {{p}})", { field: f, p: v });
    case "pick:high_stakes_conf": return t("Key field not certain enough: {{field}} ({{p}})", { field: f, p: v });
    case "pick:absent_but_chosen": return t("Probably not on the document, yet selected: {{field}} ({{p}})", { field: f, p: v });
    case "pick:present_but_none": return t("Present on the document but could not be selected: {{field}} ({{p}})", { field: f, p: v });
    case "pick:no_candidates": return t("No candidate: {{field}}", { field: f });
    case "pick:present_no_candidates": return t("Present on the document, but the code found no candidate for it: {{field}} ({{p}})", { field: f, p: v });
    case "pick:none": return t("No value: {{field}}", { field: f });
    case "pick:none_on_cut_list": {
      const [sent, found] = (p[3] ?? "").split("/");
      return t("No value, but the candidate list was cut: {{field}} ({{sent}} of {{found}} candidates went to the model)", { field: f, sent, found });
    }
    case "jev:unsupported": return t("Not supported by the model: {{field}}", { field: f });
    // 167 (review AI-10): a list left out of the JEV verification so that the request fits its size limit
    case "jev:list_omitted": return t("JEV did not check this list, to keep the request within its size limit: {{field}}; check its rows by hand", { field: f });
    // 177 (plan 170 E6): the JEV verification's field and document flags (jav/ai/policy.py); until now the raw code showed
    case "jev:absence_wrong": return t("JEV: the field was left empty, though it is on the document: {{field}} ({{p}})", { field: f, p: v });
    case "jev:off_target": return t("JEV: the value belongs to another field: {{field}} ({{p}})", { field: f, p: v });
    case "jev:wrong_kind": return t("JEV: the value is not of this field's kind: {{field}} ({{p}})", { field: f, p: v });
    case "jev:incomplete": return t("JEV: the value seems cut short: {{field}} ({{p}})", { field: f, p: v });
    case "jev:parties_swapped": return t("JEV: the supplier and the buyer seem swapped ({{p}})", { p: num(p[2]) });
    case "jev:line_items_missing_rows": return t("JEV: the document has line items the extracted list lacks ({{p}})", { p: num(p[2]) });
    // 190: the per-list questions a verification call site may name (`list_nouls`), the list as the field
    case "jev:missing_rows": return t("JEV: the document has rows of this list that the extraction lacks: {{field}} ({{p}})", { field: f, p: v });
    case "jev:extra_rows": return t("JEV: the extracted list has rows the document does not: {{field}} ({{p}})", { field: f, p: v });
    case "jev:line_items_extra_rows": return t("JEV: the extracted list has line items the document does not ({{p}})", { p: num(p[2]) });
    // 085: processing without JEV: the extracted value is printed nowhere on the document (the code's own check)
    case "source:not_found": return t("The extracted value is not printed on the document: {{field}}", { field: f });
    // 092: without JEV, an accounting field GPT is not sure enough of (below the policy's review_below)
    case "gpt:low_conf": return t("GPT is not sure enough of the value: {{field}} (probability {{p}})", { field: f, p: v });
    // 160 (review AI-6): without JEV, an accounting field whose GPT answer carried no token probability
    case "gpt:confidence_unavailable": return t("GPT's confidence cannot be measured for this value: {{field}}; check by hand", { field: f });
    case "llm:required_missing": return t("Required field missing: {{field}}", { field: f });
    // 167 (review AI-7): GPT's answer stopped at its output cap; it is not asked again
    case "llm:truncated": return t("GPT's answer was cut off at its length limit, so nothing was extracted: the document is probably too long for one extraction; check it by hand");
    case "money:separator_ambiguous": return t("Ambiguous decimal separator: {{field}}", { field: f });
    // 081: the S path's safety net: the picked number stands on the page only as a piece of a longer number
    case "money:token_cut": return t("The chosen value is only part of the number printed on the document: {{field}}", { field: f });
    // 084: the shared date reader: the printed date's day and month can be read two ways ("04/12/2022")
    case "date:order_ambiguous": return t("Uncertain order of day and month: {{field}}", { field: f });
    case "ocr:partial_pages": return t("Not all pages were recognised ({{pages}})", { pages: p[2] });
    // 167 (review AI-3): pages without a text layer of their own in a document that has one: neither read nor recognised
    case "pdf:pages_without_text": return t("Pages without a text layer of their own were not read ({{pages}} pages); look at them in the document", { pages: p[2] });
    case "ocr:no_text": return t("No text could be extracted from the document");
    // 190: a document given as text (an email's own text) had no text at all (jav/flows/flow.py load_text)
    // 190: an item's follow-up stage (the extraction of an email's own text) ended without a to-do of its own
    case `follow_up:${p[1] ?? ""}`: return t("An item's follow-up step did not finish cleanly ({{status}}); look at the item by hand", { status: p[1] ?? "" });
    case "text:empty": return t("The text given as the document is empty, so nothing was extracted from it");
    // 177: the text recognition itself could not run (jav/flows/flow.py, jav/flows/flow_detect.py)
    case "ocr:unavailable": return t("Text recognition could not run ({{why}}); look at the document by hand", { why: p[2] ?? "" });
    case "ocr:low_confidence": return t("Weak text recognition ({{p}})", { p: num(p[2]) });
    case "ocr:low_conf_words": return t("Many uncertain words in the recognition ({{p}})", { p: num(p[2]) });
    // 075: the Azure escalation of a weak scan did not run (jav/documents/ocr.py escalation_review_reasons); 121: no route, failed call
    case "ocr:escalation_blocked":
      if (p[2] === "uncertain_attempt") return t("Weak local recognition; an earlier Azure call has an uncertain outcome, so it was not repeated");
      if (p[2] === "unreachable") return t("Weak local recognition; Azure recognition is not set up for this document");
      if (p[2] === "unavailable") return t("Weak local recognition; Azure recognition failed");
      return t("Weak local recognition; Azure recognition was skipped because of the run's budget");
    // 078: a PDF attachment the reader could not read; the email's intent was still recognised
    case "attachment:unreadable": return t("A PDF attachment could not be read (corrupt, too large, or over the reading time or memory); the email's intent was still recognised");
    // 154: an attachment of an email routed as suspicious (an injected instruction); processed, but a person looks first
    case "attachment:suspicious_email": return t("An attachment of an email marked as suspicious (it may carry a hidden instruction): check the document and the email before relying on it");
    // 177: the email itself (the signal's yes band, policy email.signal_review)
    case "signal:prompt_injection": return t("The email may carry an injected instruction ({{p}}): read it before acting on it", { p: num(p[2]) });
    // 126: a suspected duplicate invoice (jav/domains/finance/duplicates.py); decided in its own panel on the review page
    case "duplicate:copy": return t("Possible copy of an earlier document (same invoice number and supplier)");
    case "duplicate:variant": return t("Possible modified version of an earlier document (same invoice number and supplier, different values)");
    case "duplicate:undecidable": return t("Possible duplicate of an earlier document (same invoice number and supplier, a value is missing)");
    // 139: another statement books the same days of the account and neither replaces the other; chosen in its own panel
    case "statement:overlap": return t("Another statement books the same days of this account: choose the valid one");
    // 129: a proposed invoice <-> statement line pair (jav/domains/finance/reconcile.py); decided in its own panel on the review page.
    // 130: a card line is compared with the invoice amount converted at the MNB rate
    case "reconcile:proposed": return t("Possible payment: a statement line and an invoice have the same amount (for a card payment, the converted amount) and a shared detail");
    // 131: the same amount alone is never a proposal; the pair is listed for a person to decide
    case "reconcile:amount_only": return t("Possible payment to decide: a statement line has exactly the invoice's amount, but nothing else ties them");
    // 136: a statement read by code from a bank's table export (jav/domains/finance/flow_statement_table.py)
    case "statement_table:unreadable_lines": return t("Some lines of the table export could not be read ({{n}}); they are left out of the statement", { n: p[2] ?? "" });
    case "statement_table:missing": return t("A required field is missing from the table export: {{field}}", { field: f });
    case "statement_table:balance_unchecked": return t("The balances cannot be checked: the export has none, and its PDF statement was not found next to it");
    // 174 (review 160 M-12): balances taken from the lines, with no total row
    case "statement_table:balance_from_lines": return t("The balances were taken from the export's own lines and it has no total row, so its first and last lines cannot be checked");
    case "statement_table:companion_mismatch": return t("The export and its PDF statement differ ({{n}}): a line is on one side only, or the PDF is of another account", { n: p[2] ?? "" });
    // 140: a statement package (jav/domains/finance/statement_package.py)
    case "statements:not_a_statement": return t("This PDF is not a bank statement ({{type}}): the statement package extracts no data from it. Remove it from the package, or process it in a document package.", { type: docTypeLabel(p[2] ?? "") });
    case "statements:other_party": return t("The statement's account belongs to another own party, and it stayed there. If it is this package's party's, move it in Settings › Own parties.");
    // 171 (plan 170, K20): the flow built no record from the document (`policy.decide`); until now the raw code showed
    case "no_invoice:": return t("No data was extracted from the document, so it has no values to check or download; its other to-dos show why");
    case "parties:same_tax_id": return t("The supplier and the buyer have the same tax ID");
    case "parties:same_name": return t("The supplier and the buyer have the same name");
    // 134: the supplier tax number is an own party's (jav/app/parties.py review_reasons)
    case "parties:own_tax_as_supplier": return t("The supplier's tax number is an own party's: the two tax numbers may be swapped, or this is an outgoing invoice");
    case "detect:low_conf": return t("Uncertain type recognition: {{type}} ({{p}})", { type: docTypeLabel(p[2]), p: v });
    case "detect:detail_open": return t("The detailed type cannot be decided (category: {{type}}); choose it manually", { type: docTypeLabel(p[2]) });
    case "detect:no_type_pack": return t("There is no data extraction for this document type ({{type}}); check it manually", { type: docTypeLabel(p[2]) });
    // 177: the recognition gave no result and named no reason of its own (jav/flows/flow_detect.py)
    case "detect:no_result": return t("Type recognition gave no result; choose the type by hand");
    // 090: the type / issuer cross-check in code (configs/policy.json detect_issuer): the type is kept
    case "detect:issuer_mismatch": return t("The type ({{type}}) presumes a Hungarian issuer, but the recognition says the issuer is not Hungarian; check the type", { type: docTypeLabel(p[2]) });
    case "detect_detail:low_conf": return t("Uncertain detailed type: {{type}} ({{p}})", { type: docTypeLabel(p[2]), p: v });
    // 149: the direction the own parties give contradicts the detailed type
    case "detect_detail:direction_mismatch": return t("The detailed type ({{type}}) contradicts the parties: by them the invoice is {{direction}}; check the type", {
      type: docTypeLabel(p[2]), direction: p[3] === "outgoing" ? t("outgoing") : p[3] === "incoming" ? t("incoming") : p[3] ?? "" });
    case "detect_detail:second_option": return t("For the detailed type, the second option is also close: {{type}}", { type: docTypeLabel(p[2]) });
    // 086: type recognition by GPT (processing without JEV)
    case "detect:gpt_failed": return t("Type recognition by GPT failed ({{why}}); choose the type by hand", { why: p[2] ?? "" });
    case "detect:confidence_unavailable": return t("The confidence of the recognised type cannot be measured: {{type}}; check it by hand", { type: docTypeLabel(p[2]) });
    case "detect_detail:gpt_failed": return t("Recognising the detailed type by GPT failed ({{why}}); choose it by hand", { why: p[2] ?? "" });
    case "detect_detail:confidence_unavailable": return t("The confidence of the detailed type cannot be measured: {{type}}; check it by hand", { type: docTypeLabel(p[2]) });
    case "intent:low_conf": return t("Uncertain email intent: {{intent}} ({{p}})", { intent: intentLabel(p[2]), p: v });
    case "intent:no_result": return t("The email's intent could not be recognised");
    // 089: the intent recognised by GPT (processing without JEV)
    case "intent:gpt_failed": return t("GPT intent recognition failed ({{why}}); read the email and decide by hand", { why: p[2] ?? "" });
    case "intent:confidence_unavailable": return t("The confidence of the email's intent cannot be measured; check it by hand");
    // 086: processing without JEV, before 089 (older runs): the intent was not recognised at all
    case "intent:jev_off": return t("Processing without JEV: the system does not recognise the email's intent; read it and decide by hand");
    // 073: task proposals from an e-mail (jav/domains/email/flow_email.py); until now these showed the raw code
    case "tasks:proposed": return t("{{n}} task proposal(s) awaiting a decision", { n: p[2] ?? "" });
    case "tasks:failed": return t("Task proposal failed ({{why}})", { why: p[2] ?? "" });
    // 120: the to-dos of Word, Excel, text and continuing PDF documents (jav/flows/flow_native.py)
    case "native:reading": return t("The document is not fully readable ({{status}}); check the source and the gaps", { status: NATIVE_STATUS[p[2]] ?? p[2] ?? "" });
    case "native:interpretation": return t("The extraction did not succeed ({{status}}); check the reason", { status: NATIVE_STATUS[p[2]] ?? p[2] ?? "" });
    case "native:no_facts": return t("The document produced no facts");
    case "native:interpretation_gaps": return t("The extraction reported a gap");
    // 124: a scan read from its Azure recognition (weak word confidences), or the native step's own Azure call
    // did not run (jav/flows/flow_native.py review_native)
    case "native:recognition":
      if (p[2] === "low_confidence") return t("Weak Azure recognition ({{p}})", { p: num(p[3]) });
      if (p[2] === "low_conf_words") return t("Many uncertain words in the Azure recognition ({{p}})", { p: num(p[3]) });
      if (p[3] === "uncertain_attempt") return t("An earlier Azure call has an uncertain outcome, so it was not repeated; local recognition was used");
      if (p[3] === "unreachable") return t("Azure recognition is not set up for this document; local recognition was used");
      if (p[3] === "unavailable") return t("Azure recognition failed; local recognition was used");
      return t("Azure recognition was skipped because of the run's budget; local recognition was used");
    // 123: facts left out of a received answer for breaking the presence rule
    case "native:discarded_facts": return t("{{n}} proposed facts were malformed and left out; check the source", { n: p[2] ?? "" });
    case "native:grounding": return t("A fact is not found word for word in the source");
    case "native:claim": return t("A fact is not certain ({{state}})", { state: NATIVE_STATUS[p[2]] ?? p[2] ?? "" });
    case "native:fact": {
      const n = Number(p[2]) + 1;
      if (p[3] === "unsupported") return t("JEV does not support fact {{n}} ({{p}})", { n, p: num(p[4]) });
      if (p[3] === "uncertain") return t("JEV is uncertain about fact {{n}} ({{p}})", { n, p: num(p[4]) });
      return t("Fact {{n}} has a warning; check it", { n });
    }
  }
  // 090: a field check's to-do names its field third (`validator:taxid.unrecognized:supplier_tax_id`)
  if (p[0] === "validator" && p.length === 3 && FIELD[p[2]]) return `${checkText(p[1] ?? "")}: ${fieldLabel(p[2])}`;
  if (p[0] === "validator") return checkText(p[1] ?? "", p.slice(2).join(":") || null);
  // 160: in processing without JEV a JEV question asked anyway is refused before it is sent
  if (code === "jev_unavailable:disabled") return t("The JEV question was not sent: this processing runs without JEV, on GPT only; check by hand");
  if (p[0] === "jev_unavailable") return t("JEV was unavailable ({{why}}); check manually", { why: p.slice(1).join(":") });
  if (p[0] === "llm" && p[1] === "failed") return t("GPT extraction failed ({{why}})", { why: p[2] ?? "" });
  // 177: an amount or a quantity of the record that cannot be read as a number (`<field>:unparseable:<raw>`, jav/ai/models.py)
  if (p[1] === "unparseable") return t("A number cannot be read: {{field}}", { field: fieldPathLabel(p[0]) });
  // 177: a value the type pack does not allow for the field (`<field>:not_in_enum:<value>`, jav/ai/models.py)
  if (p[1] === "not_in_enum") return t("The value is not one the field allows: {{field}}", { field: fieldPathLabel(p[0]) });
  return code;
}

/** 177: a field of the record by its path: a list's row (`line_items[3].gross_amount`: the list, its row counted from
 *  1, and its column), or a simple field. */
function fieldPathLabel(path: string): string {
  const m = path.match(/^(\w+)\[(\d+)\]\.(\w+)$/);
  return m ? t("{{list}}, row {{row}}: {{column}}", { list: fieldLabel(m[1]), row: Number(m[2]) + 1, column: columnLabel(m[3]) })
    : fieldLabel(path);
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

/** 231 (stage D, D-c6): a sentence the service wrote for a person (a problem a check lists), in the chosen language:
 *  where it applies first ("rule x@1: row 2: …"), then the sentence; one not written as a template stays as it is. */
export function saidText(s: Said): string {
  const params = Object.fromEntries(Object.entries(s.params ?? {}).map(([k, v]) => [k, s.labels?.includes(k) ? t(v) : v]));
  const own = s.template ? t(s.template, params) : s.text;
  return s.within ? `${saidText(s.within)}: ${own}` : own;
}

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

/** 167 (review 160 U-13): an amount in a table: always two decimals and grouped thousands, a four-digit one too
 *  ("1 200,50", not "1200,5"); a non-number stays unchanged. */
export function moneyText(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  return Number.isFinite(n)
    ? n.toLocaleString(getLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: "always" } as unknown as Intl.NumberFormatOptions)
    : String(v);
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
  empty: "Empty document batch", start: "Start trial run", blocked: "Cannot start",
  rerun: "Failed or stopped run: rerun", done: "Released: download result", release: "Approve and release",
  go_live: "Trial OK: live run",
  // 132: a reconciliation package's steps (jav/domains/finance/reconcile_package.py `next_step`)
  reconcile_empty: "No statement line in the scope", reconcile_result: "Reconciliation result",
  // 181: an email routing package's steps (jav/domains/email/email_routing.py `_next`)
  routing_empty: "Nothing to route", routing_done: "Routed",
  // 191: a quote package's steps (jav/domains/quotes/quote_package.py `_next_of`)
  quote_request_missing: "The request cannot be read", quote_compose: "Compose the quote",
  quote_propose: "Ask for the proposal", quote_proposing: "The proposal is being made", // B4c
  quote_approve: "Approve the quote", // 192 B5
  // 231 (A6): a process pack's case container (jav/app/process_runtime.py `_next`)
  case_open: "Open the case", case_closed: "The case is closed",
  // 231 (A7e): the send and the reply (jav/app/sending.py, jav/app/replies.py)
  case_send: "Send", case_send_settle: "Say whether it arrived", case_send_failed: "The send failed",
  case_reply_wait: "Waiting for the reply", case_follow_up: "Follow up the reply",
  // 231 (U2c): a step that runs a case of another process waits for it (jav/app/sub_cases.py)
  case_sub_case: "Continue in its sub-case",
});

/** The package's next step in the chosen language (057): from the service's code and parameters; for an unknown code,
 *  the service's (Hungarian) label. Both the package header and the work package list column use it. */
export function stepLabel(code: string, params: Record<string, unknown> | undefined, fallback: string): string {
  if (code === "running") return t("Running: {{done}}/{{total}}", { done: params?.done ?? 0, total: params?.total ?? 0 });
  if (code === "review") return t("Review: {{n}} to-dos", { n: params?.n ?? 0 });
  // 160-C S2: items added after the run wait for processing
  if (code === "pending") return t("{{n}} new item(s) to process", { n: params?.n ?? 0 });
  // 150: after a trial with to-dos the step is going live; the trial's to-dos are only information
  if (code === "go_live" && params?.trial_reasons) return t("Trial finished: live run ({{n}} to-dos in the trial)", { n: params.trial_reasons });
  if (code === "reconcile_pair") return t("Pairing: {{n}} open lines", { n: params?.n ?? 0 });
  if (code === "reconcile_approved") return t("Approved: version {{n}}", { n: params?.version ?? "" }); // 145
  if (code === "routing_decide") return t("Route the documents: {{n}} to decide", { n: params?.n ?? 0 }); // 181
  if (code === "quote_request_check") return t("Check the request: {{n}} gap(s)", { n: params?.n ?? 0 }); // 191
  if (code === "quote_compose" && params?.n) return t("Compose the quote: {{n}} to settle", { n: params.n }); // 192
  if (code === "quote_approved") return t("Approved: version {{n}}", { n: params?.version ?? "" }); // 192
  // D-f4: an assessment's field check waits for its freeze (with the disagreements still to settle)
  if (code === "facts_check") return params?.n ? t("Check the facts: {{n}} to settle", { n: params.n }) : t("Check and freeze the facts");
  if (code === "missing_facts") return t("Get the missing facts: {{n}}", { n: params?.n ?? 0 }); // D-f5
  if (code === "decision_make" && typeof params?.title === "string") return t("Decide: {{what}}", { what: t(params.title) }); // D-f6
  if (code === "letter_accept") return t("Accept the letter"); // D-f8
  return Object.prototype.hasOwnProperty.call(STEP_LABEL, code) ? STEP_LABEL[code] : fallback;
}

/** A pre-run blocker / warning in the chosen language (from the service's code; the file name is a parameter). */
export function blockerText(b: { code: string; message: string }): string {
  const name = b.message.includes(": ") ? b.message.slice(b.message.indexOf(": ") + 2) : "";
  switch (b.code) {
    case "no_items": return t("The document batch has no items.");
    // 080: the processing settings replace the recipe; a package without settings runs with the default ones
    case "recipe_changed": return t("The processing changed since the settings were saved; save the settings again.");
    case "recipe_retired": return t("The batch uses a retired version of the processing; switch it to the current processing.");
    case "unsupported_item": return t("The processing does not handle: {{name}}", { name });
    case "source_missing": return t("Missing source: {{name}}", { name });
    case "source_changed": return t("The source content changed since it was added: {{name}}", { name });
    case "instance_damaged": return t("The copy kept when it was added is missing or damaged: {{name}}", { name });
    case "original_changed": return t("The original file has changed since it was added; the copy kept then is processed: {{name}}", { name });
    case "original_missing": return t("The original file has disappeared since it was added; the copy kept then is processed: {{name}}", { name });
    default: return b.message;
  }
}

/** The package's items as text (058): documents and emails separately, so that a mailbox package does not say
 *  „irat” (document). */
export function itemCountText(items: { kind: string }[]): string {
  const mails = items.filter((i) => i.kind === "email").length;
  const docs = items.length - mails;
  if (mails && docs) return t("{{docs}} documents, {{mails}} emails", { docs, mails });
  return mails ? t("{{n}} emails", { n: mails }) : t("{{n}} documents", { n: docs });
}

// 058: the email intent's name from the registry (configs/intents.json), in the chosen language — no code name is shown
const INTENT: Record<string, string> = tmap(Object.fromEntries(intentRegistry.intents.map((i) => [i.key, i.display_name])));
export const intentLabel = (key: string | null | undefined): string => (key ? INTENT[key] ?? key : "");

/** Labels of the processing settings (058; 080: the path by what it does, the owner's decision of 2026-10-01): a short
 *  value without code names; the long explanation is in the settings editor and on Settings › Processing. */
export const PARAM_LABEL: Record<string, string> = tmap({ path: "Processing path", arm: "Path", doc_type: "Document type", jev_cache: "Earlier answers", tasks: "Task proposal", azure_ocr: "Azure recognition", jev: "Use of JEV",
  unknown_documents: "Unknown PDFs",  // 120
  email_text: "Quote requests from the email's text" });  // 190
const PARAM_SHORT: Record<string, string> = tmap({
  "jev:on": "on",
  "jev:off": "off — GPT only (OpenAI)",
  // 090: the path and the use of JEV as one choice (`path`, shown only)
  "path:auto": "Automatic (recommended) — JEV and GPT",
  "path:S": "JEV where possible — cheaper, no line items; GPT elsewhere (S)",
  "path:G": "GPT + JEV — with line items (G)",
  "path:gpt": "GPT only, without JEV (OpenAI)",
  "path:jev": "With JEV (recommended)",
  "arm:auto": "Automatic (recommended)",
  "arm:S": "JEV where possible — cheaper, no line items; GPT elsewhere (S)",
  "arm:G": "GPT + JEV — with line items (G)",
  "jev_cache:reuse": "earlier answer may be reused",
  "jev_cache:live": "always a live call",
  "tasks:off": "off",
  "tasks:propose": "on (GPT)",
  "azure_ocr:on": "for weak scans",
  "azure_ocr:off": "off",
  // 120: a text PDF without a fitting type pack (written with codepoints for the language guard)
  "unknown_documents:facts": "general facts (GPT + JEV)",
  "unknown_documents:review": "stops for manual review",
  // 190: the extraction of a quote request written in the email itself (the owner's decision of 2026-10-21: on)
  "email_text:extract": "extracted (GPT + JEV)",
  "email_text:off": "not extracted",
});
/** 080: the item kind a setting acts on (the path, Azure and the document type on documents, task proposals on
 *  emails); a setting not listed acts on every item. With the package's item kinds known, a setting that cannot act on
 *  any of them is not shown. */
const PARAM_KIND: Record<string, string> = { arm: "document", azure_ocr: "document", doc_type: "document", tasks: "email",
  unknown_documents: "document", email_text: "email" };
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

const KIND_BUDGET: Record<string, string> = tmap({ email: "per email", document: "per PDF document",
  statement_table: "per statement from a table export" });  // 136: read by code, so its budget is empty
/** The per-item budget line by line (one line per item kind), e.g. „levelenként: JEV legfeljebb 0,05 USD” (per email:
 *  JEV at most 0.05 USD). */
export function itemBudgetLines(r: Recipe, params: Record<string, string>, only?: string[]): string[] {
  // 080: `only` — the package's item kinds; the other kinds' lines are left out
  const kinds = (r.max_item_usd_by_kind ? Object.keys(r.max_item_usd_by_kind) : [undefined])
    .filter((kind) => !kind || !only?.length || only.includes(kind));
  return kinds.map((kind) => {
    const amounts = Object.entries(itemBudget(r, params, kind))
      .map(([p, v]) => t("{{provider}} up to {{amount}}", { provider: providerName(p), amount: usdBudget(v) })).join(", ") || t("none");
    return kind ? `${KIND_BUDGET[kind] ?? kind}: ${amounts}` : t("per item: {{amounts}}", { amounts });
  });
}

/** 080 (the pre-start overview, F-külső-kapcsolók): what a run will do, one line per service — the budget maximum and
 *  what it is for, from the readiness check's `plan` and `budget`. A service with no budget is said not to be called. */
export function planLines(plan: RunPlan, budget: Record<string, string>): string[] {
  const amount = (p: string) => Number(budget[p] ?? 0);
  const head = (p: string) => t("{{provider}} up to {{amount}}", { provider: providerName(p), amount: usdBudget(budget[p]) });
  const join = (parts: (string | false)[]) => parts.filter(Boolean).join("; ");
  const out: string[] = [];
  if (plan.documents) out.push(t("Local text recognition: free, on every document."));
  // 136: a statement from a bank's table export is read by code; no service is called for it
  if (plan.statement_tables) out.push(t("{{n}} statement(s) from a table export: read by code, free.", { n: plan.statement_tables }));
  if (amount("jev") > 0) {
    out.push(`${head("jev")}: ${join([
      plan.documents > 0 && t("type recognition and data extraction of {{n}} document(s)", { n: plan.documents }),
      plan.emails > 0 && t("intent recognition of {{n}} email(s)", { n: plan.emails }),
      plan.jev_reuse ? t("questions asked before are not paid for again") : t("every question is a live call; earlier answers do not count"),
    ])}.`);
  }
  if (plan.jev === false) {
    // 086: processing without JEV — no JEV budget, so not even a stray JEV call could start
    out.push(t("JEV: not called (switched off)."));
  }
  if (amount("openai") > 0 && plan.jev === false) {
    out.push(`${head("openai")}: ${join([
      plan.documents > 0 && t("type recognition and extraction of {{n}} document(s) on the G path, checked by the code", { n: plan.documents }),
      plan.emails > 0 && t("intent recognition of {{n}} email(s)", { n: plan.emails }),  // 089: by GPT without JEV
      plan.tasks_emails > 0 && t("task proposal for {{n}} email(s)", { n: plan.tasks_emails }),
      // 190: the extraction of a quote request written in the email itself (spent only on such emails)
      (plan.text_emails ?? 0) > 0 && t("{{n}} email(s): a quote request written in the email is read from its text", { n: plan.text_emails }),
      // 192: an Excel or CSV request list attached to a quote request email (spent only on such a list)
      (plan.text_tables ?? 0) > 0 && t("{{n}} table attachment(s): a request list attached to a quote request is read with it", { n: plan.text_tables }),
    ])}.`);
  } else if (amount("openai") > 0) {
    out.push(`${head("openai")}: ${join([
      plan.paths.G > 0 && (plan.arm === "S"  // 082: the S path runs on G where the type has no JEV path
        ? t("{{n}} documents on the G path, because their type has no JEV path", { n: plan.paths.G })
        : t("{{n}} document(s) on the G path", { n: plan.paths.G })),
      plan.paths.unknown > 0 && t("{{n}} document(s) of a type not yet known, if the recognised type takes the G path", { n: plan.paths.unknown }),
      plan.tasks_emails > 0 && t("task proposal for {{n}} email(s)", { n: plan.tasks_emails }),
      // 190: the extraction of a quote request written in the email itself (spent only on such emails)
      (plan.text_emails ?? 0) > 0 && t("{{n}} email(s): a quote request written in the email is read from its text", { n: plan.text_emails }),
      // 192: an Excel or CSV request list attached to a quote request email (spent only on such a list)
      (plan.text_tables ?? 0) > 0 && t("{{n}} table attachment(s): a request list attached to a quote request is read with it", { n: plan.text_tables }),
    ])}.`);
  } else if (plan.documents || plan.emails) {
    out.push(plan.documents ? t("OpenAI: not called, every document runs on the S path.") : t("OpenAI: not called."));
  }
  if (amount("azure_di") > 0) out.push(`${head("azure_di")}: ${t("only for poor-quality scans, instead of the local recognition")}.`);
  else if (plan.documents) out.push(t("Azure DI: not called (switched off)."));
  return out;
}

/** The selectable email intents in registry order, in the chosen language (058 K5.1: correcting the intent by hand). */
export const intentOptions = (): { value: string; label: string }[] =>
  intentRegistry.intents.map((i) => ({ value: i.key, label: t(i.display_name) }));

/** 058 K5.3: the names of the task proposal actions (configs/email_tasks.json), in the chosen language. */
export const TASK_ACTION: Record<string, string> = tmap(emailTasks.actions as Record<string, string>);
