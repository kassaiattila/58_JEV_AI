// 218 (plan G-process-core P3e): Settings › Rules — how the system decides on its own, read only. The section has its own
// address after Processing; each decision is a row within four lines (its title, what it decides, its values, its rule
// files, its count); a title opens the whole rule below the table; every text of the rules' description is translated.
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import intents from "../../../../configs/intents.json";
import help from "../../../../configs/rule_help.json";
import { api, type DsColumn, type DsPage, type DsRow } from "../../api";
import english from "../../i18n/en-native.json";
import hungarian from "../../i18n/hu-native.json";
import { setLanguage } from "../../i18n";
import { nextFlowText } from "../../labels";
import { parseRoute } from "../../route";
import { Settings } from "../Settings";
import { settingsSections } from "../../logic/settingsSections";
import { valueText, type RuleValue } from "./RulesPanel";

const hu = hungarian as Record<string, string>;
const en = english as Record<string, string>;
const fill = (text: string, params: Record<string, string>) => text.replace(/\{\{(\w+)\}\}/g, (_, k: string) => params[k]);
const intentName = (key: string) => intents.intents.find((i) => i.key === key)?.display_name ?? key;
const points = help.points as Record<string, { area: string; title: string; what: string; not_for: string; values: { key: string; label: string }[] }>;
const label = (code: string, key: string) => points[code].values.find((v) => v.key === key)?.label ?? key;

const COLUMNS: DsColumn[] = [
  { key: "area", label: "Area", kind: "enum", hidden: false, labels: help.areas },
  { key: "decision", label: "Decision", kind: "text", hidden: false, labels: null },
  { key: "values", label: "Rule values", kind: "text", hidden: false, labels: null },
  { key: "files", label: "Rule files", kind: "text", hidden: false, labels: null },
  { key: "decisions", label: "Decisions", kind: "number", hidden: false, labels: null },
  { key: "what", label: "What it decides", kind: "text", hidden: true, labels: null },
  { key: "not_for", label: "What it is not for", kind: "text", hidden: true, labels: null },
  { key: "current", label: "With the rules in use now", kind: "number", hidden: true, labels: null },
  { key: "last_at", label: "Last decision", kind: "datetime", hidden: true, labels: null },
];
const POLICY = { file: "policy.json", title: "Shared decision thresholds", version: "1.25.0", dated: "2026-10-21", count: null,
  since: "2026-10-24T07:00:00+00:00" };

function row(code: string, values: RuleValue[], extra: Partial<DsRow> = {}): DsRow {
  const p = points[code];
  return { _key: code, area: p.area, decision: p.title, what: p.what, not_for: p.not_for, values: "", files: "",
    decisions: 0, current: 0, last_at: null, _values: values, _files: [POLICY], ...extra };
}
// 224: an email's next step reads the email domain's own rule file besides the shared bands
const EMAIL = { file: "email.json", title: "Email routes", version: "1.0.0", dated: "2026-10-24", count: null, since: null };
const value = (code: string, key: string, format: RuleValue["format"], v: unknown, file = "policy.json"): RuleValue =>
  ({ file, key, label: label(code, key), format, value: v });

const TYPE = row("detect.doc_type", [
  value("detect.doc_type", "bands.default.choice_human_max_conf", "percent", 0.6),
  value("detect.doc_type", "bands.default.choice_second_min_gap", "points", 0.2),
  value("detect.doc_type", "bands.default.uncertain_review", "yes_no", false),
], { decisions: 13, current: 12, last_at: "2026-10-24T08:00:00+00:00" });
const NEXT = row("email.next_flow", [
  value("email.next_flow", "intent_route", "routes", [
    [intentName("quote_request"), { code: "m2:quote_request", reads_text: true }],
    [intentName("szamlakuldes"), { code: "human:fetch_document", reads_text: false }],
  ], "email.json"),
  value("email.next_flow", "sent_route", "route", { code: "archive:sent", reads_text: false }, "email.json"),
], { _files: [POLICY, EMAIL] });
const DETAIL = row("detect.detail_type", [
  value("detect.detail_type", "bands.default.choice_human_max_conf", "percent", 0.6),
]);
const GATE = row("workflow.budget_gate", [{ file: "recipes.json", key: "recipes[processing].max_item_usd_by_kind.email.*",
  label: label("workflow.budget_gate", "recipes[processing].max_item_usd_by_kind.email.*"), format: "usd", value: [["JEV", "0.05"]] }],
{ _files: [{ file: "recipes.json", title: "Processing recipes and their cost caps", version: "1.15.0", dated: null, count: null, since: null }] });

function page(rows: DsRow[]): DsPage {
  return { dataset: { name: "rules", label: "Rules", scope: [], optional_scope: [] } as DsPage["dataset"], columns: COLUMNS, rows,
    total: rows.length, matched: rows.length, offset: 0, limit: 100, facets: {} };
}

beforeEach(async () => {
  await setLanguage("hu");
  vi.spyOn(api, "datasetQuery").mockResolvedValue(page([TYPE, DETAIL, NEXT, GATE]));
});
afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

describe("Settings › Rules (218)", () => {
  it("is its own section after Processing, with its own address", () => {
    const keys = settingsSections().map((s) => s.key);
    expect(keys.indexOf("rules")).toBe(keys.indexOf("recipes") + 1);
    expect(parseRoute("#/settings/rules")).toEqual({ view: "settings", section: "rules" });
  });

  it("lists each decision within four lines: its title, what it decides, its values, its files and its count", async () => {
    render(<Settings section="rules" />);
    expect(screen.getByRole("heading", { level: 2, name: hu["Defaults"] })).toBeTruthy();  // 231 (U4d): named Defaults
    const open = await screen.findByRole("button", { name: hu[points["detect.doc_type"].title] });
    const tr = open.closest("tr") as HTMLElement;
    const cells = within(tr);
    expect(cells.getByText(hu["Document recognition"])).toBeTruthy();
    expect(tr.textContent).toContain(hu[points["detect.doc_type"].what]);
    // a threshold's label reads on into its value; a yes or no after a colon
    expect(tr.textContent).toContain(`${hu[label("detect.doc_type", "bands.default.choice_human_max_conf")]} 60\u00a0%`);
    expect(tr.textContent).toContain(`${hu[label("detect.doc_type", "bands.default.choice_second_min_gap")]} ${fill(hu["{{n}} percentage points"], { n: "20" })}`);
    expect(tr.textContent).toContain(`${hu[label("detect.doc_type", "bands.default.uncertain_review")]}: nem`);
    expect(tr.textContent).toContain(`${hu["Shared decision thresholds"]} 1.25.0`);
    expect(cells.getByText("13")).toBeTruthy();
    // the area heads its group once (a screen reader still hears it on each row); no decision yet is a quiet zero
    const detail = (await screen.findByRole("button", { name: hu[points["detect.detail_type"].title] })).closest("tr") as HTMLElement;
    expect(detail.querySelector('td[data-col="area"] .sr-only')?.textContent).toBe(hu["Document recognition"]);
    expect(tr.querySelector('td[data-col="area"] .sr-only')).toBeNull();
    expect(detail.querySelector('td[data-col="decisions"] .count-zero')?.textContent).toBe("0");
    // each long cell is clamped, the whole text in its tooltip
    const clamps = [...tr.querySelectorAll<HTMLElement>(".dt-clamp")];
    expect(clamps.map((c) => c.style.webkitLineClamp)).toEqual(["2", "4", "4"]);
    // an amount by provider, in the chosen language's figures
    const gate = (await screen.findByRole("button", { name: hu[points["workflow.budget_gate"].title] })).closest("tr") as HTMLElement;
    expect(gate.textContent).toContain(`${hu[label("workflow.budget_gate", "recipes[processing].max_item_usd_by_kind.email.*")]}: JEV 0,05 USD`);
  });

  it("opens a decision's whole rule below the table, and closes it", async () => {
    render(<Settings section="rules" />);
    expect(await screen.findByText(hu["Choose a decision's title to read its whole rule."])).toBeTruthy();
    const open = await screen.findByRole("button", { name: hu[points["email.next_flow"].title] });
    fireEvent.click(open);
    expect(open.getAttribute("aria-expanded")).toBe("true");
    const sheet = screen.getByRole("region", { name: hu[points["email.next_flow"].title] });
    expect(document.activeElement).toBe(within(sheet).getByRole("heading", { level: 3 }));
    expect(sheet.textContent).toContain(hu["Emails"]);
    expect(sheet.textContent).toContain(fill(hu["Not for: {{text}}"], { text: hu[points["email.next_flow"].not_for] }));
    // each intent's next step is its own line, named as everywhere else
    const steps = within(sheet).getAllByRole("listitem").map((li) => li.textContent);
    expect(steps).toContain(`${intentName("quote_request")} → ${nextFlowText("m2:quote_request", true)}`);
    expect(steps).toContain(`${intentName("szamlakuldes")} → ${nextFlowText("human:fetch_document")}`);
    expect(within(sheet).getByText(hu[label("email.next_flow", "sent_route")]).nextElementSibling?.textContent)
      .toBe(nextFlowText("archive:sent"));
    const file = steps.find((s) => s?.includes("policy.json")) ?? "";
    expect(file).toContain(fill(hu["version {{version}} of {{date}}"], { version: "1.25.0", date: new Date("2026-10-21T00:00:00").toLocaleDateString("hu-HU") }));
    expect(file).toContain(hu["in use here since {{when}}"].split("{{when}}")[0]);
    expect(steps.find((s) => s?.includes("email.json")) ?? "").toContain(hu["Email routes"]);
    expect(sheet.textContent).toContain(hu["No decision of this kind has been recorded yet."]);
    fireEvent.click(within(sheet).getByRole("button", { name: hu["Close"] }));
    expect(screen.queryByRole("region", { name: hu[points["email.next_flow"].title] })).toBeNull();
    expect(open.getAttribute("aria-expanded")).toBe("false");
  });

  it("names a rule file no run has used yet, counts the decisions, and keeps the open rule on a language switch", async () => {
    render(<Settings section="rules" />);
    fireEvent.click(await screen.findByRole("button", { name: hu[points["workflow.budget_gate"].title] }));
    const gate = screen.getByRole("region", { name: hu[points["workflow.budget_gate"].title] });
    expect(gate.textContent).toContain(`${fill(hu["version {{version}}"], { version: "1.15.0" })} · ${hu["no run or decision has used it here yet"]}`);
    fireEvent.click(screen.getByRole("button", { name: hu[points["detect.doc_type"].title] }));
    const type = screen.getByRole("region", { name: hu[points["detect.doc_type"].title] });
    expect(type.textContent).toContain(fill(hu["{{n}} decisions recorded, {{current}} of them with the rules in use now; the last on {{when}}."],
      { n: "13", current: "12", when: new Date("2026-10-24T08:00:00+00:00").toLocaleString("hu-HU", { dateStyle: "short", timeStyle: "short" }) }));
    await act(() => setLanguage("en"));
    expect(screen.getByRole("region", { name: points["detect.doc_type"].title }).textContent).toContain(points["detect.doc_type"].what);
  });

  it("formats each kind of value", () => {
    const v = (format: RuleValue["format"], x: unknown): RuleValue => ({ file: "f", key: "k", label: "l", format, value: x });
    expect(valueText(v("percent", 0.93))).toBe("93\u00a0%");
    expect(valueText(v("yes_no", true))).toBe("igen");
    expect(valueText(v("number", 8))).toBe("8");
    expect(valueText(v("name", "Azure DI"))).toBe("Azure DI");
    expect(valueText(v("usd", [["JEV", "0.07"], ["OpenAI", "0.15"]]))).toBe("JEV 0,07 USD, OpenAI 0,15 USD");
  });

  it("has an English source and a Hungarian translation for every text of the rules' description", () => {
    const texts = [...Object.values(help.areas), ...Object.values(help.files)];
    for (const p of Object.values(points)) {
      texts.push(p.title, p.what, p.not_for, ...p.values.map((x) => x.label));
    }
    // 231 (U2z; the owner's decision of 2026-10-28): the English shows the source, saying batch for a work package
    const shown = (text: string) => text.replace(/\bwork package/g, "document batch").replace(/\bpackage\(s\)/g, "batch(es)")
      .replace(/\bpackages\b/g, "batches").replace(/\bpackage\b/g, "batch");
    for (const text of texts) {
      expect(en[text], text).toBe(shown(text));
      expect(hu[text]?.trim(), text).toBeTruthy();
    }
  });
});
