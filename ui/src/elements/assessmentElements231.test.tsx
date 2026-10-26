// 231 (stage D, D-f5): an assessment's calculation. The rules' evaluation shows its verdict as a mark, the facts it
// missed in the to-do colour, each unit's outcomes and the rules that gave them; the premium shows each line, a module's
// total and the total under the ledger's rule; the earlier versions are a fold; and the wait for missing facts says what
// is missing and by when, and takes "they will not come" only with a reason. Invented data, a mocked service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CalculationData, type CaseView, type EvaluationData, type MissingInfoData } from "../api";
import type { Catalogue } from "../api/products";
import { setLanguage } from "../i18n";
import { elementOf } from "./registry";

beforeEach(async () => { await setLanguage("en"); setActor("Minta Anna"); });
afterEach(() => { vi.restoreAllMocks(); });

const CASE = "wp-0000000d0f50";
const CAT: Catalogue = {
  id: "property", version: "1.5.0", levels: ["holder", "site", "asset_group"],
  facts: { accounting_method: { type: "code", level: "holder", title: "Accounting method", unit: null, currency: null, options: null } },
  outcomes: {
    verdict: { type: "code", title: "Verdict", combine: "worst", unit: null, currency: null, options: ["allow", "unknown", "refer", "refuse"] },
    deductible: { type: "money", title: "Deductible", combine: "max", unit: null, currency: "HUF", options: null },
  },
  labels: { holder: "Policyholder", site: "Site", allow: "Allow", property: "Property cover" },
};
const HUF = (amount: string) => ({ amount, currency: "HUF" });

function show(type: string, step: string, data: unknown, uses: string, title: string, state = "done") {
  const page: CaseView = {
    case: { id: CASE, pack: "insurance_offer", version: "1.2.0", title: "Insurance quote", name: "Minta Kft.", status: "open" },
    steps: { [step]: { title, uses, start: "auto", state, phase: null, waiting_for: null, awaiting_start: false, note: null, result: null, actions: [] } },
    tabs: [{ id: "calculation", label: "Calculation and versions", elements: [{ type, step, data }] }], next: null,
  };
  render(<>{elementOf(type)!.render({ caseId: CASE, element: page.tabs[0].elements[0], page, onChanged: () => {} })}</>);
}

const evaluation = (verdict: string, missing: EvaluationData["latest"] extends infer L ? L extends { missing: infer M } ? M : never : never): EvaluationData => ({
  versions: [{ version: 2, input_version: 3, made_at: "2026-10-26T10:00:00+00:00", verdict, missing: missing.length, blockers: 0 },
             { version: 1, input_version: 2, made_at: "2026-10-26T09:00:00+00:00", verdict: "unknown", missing: 1, blockers: 0 }],
  latest: { version: 2, input_version: 3, verdict, modules: ["property"], modules_said: true, missing, blockers: [], product: "inv@1",
    units: [{ unit_id: "u-1", level: "holder", named: { company_name: "Minta Kft." }, combined: { verdict, deductible: HUF("100000") },
      rules: { "inv_claims@1": { matched: [2], outcomes: { verdict }, missing: [] } } }] },
  catalogue: CAT, rules: { "inv_claims@1": { title: "Claims history", kind: "eligibility", source: { document: "inv_general@1", page: 3 } } },
});

describe("the rules' evaluation", () => {
  it("shows the verdict, each unit's outcomes, the rules that gave them and the earlier versions", async () => {
    show("evaluation", "evaluate", evaluation("allow", []), "rule_evaluation@1", "Rules");
    expect((await screen.findByText("Allowed")).className).toBe("status s-done");
    expect(screen.getByText(/^Version 2, from the checked input's version 3; the modules evaluated: Property cover\.$/)).toBeTruthy();
    const table = screen.getByRole("table", { name: "Each unit's outcomes" });
    expect(table.textContent).toContain("Minta Kft.");
    expect(table.textContent).toContain("Deductible: 100,000 HUF");
    expect(table.textContent).toContain("Claims history");
    expect(screen.getByText("Earlier versions (1)")).toBeTruthy();
  });

  it("names the facts it missed in the to-do colour", async () => {
    show("evaluation", "evaluate", evaluation("unknown", [{ unit_id: "u-1", fact: "accounting_method", title: "Accounting method" }]),
      "rule_evaluation@1", "Rules");
    expect((await screen.findByText("Not known: facts are missing", { selector: ".status" })).className).toBe("status s-warn");
    expect(screen.getByText("Accounting method of Minta Kft. is missing").className).toBe("todo-text");
  });
});

describe("the premium", () => {
  it("shows each line, the module's total and the total under the ledger's rule", async () => {
    const data: CalculationData = {
      versions: [{ version: 1, input_version: 2, made_at: "2026-10-26T10:00:00+00:00", total: HUF("487000"), blockers: 0 }],
      latest: { version: 1, evaluation_version: 2, tariff_ref: "inv_tariff@1", modules: ["property"], total: HUF("487000"),
        subtotal: HUF("470000"), policy_minimum_applied: false, blockers: [],
        lines: [{ unit_id: "u-11", module: "property", basis: HUF("180000000"), base: HUF("144000"),
          steps: [{ name: "claims", factor: "1.1", after: HUF("158400") }], amount: HUF("158400") }],
        module_totals: { property: { lines: HUF("158400"), minimum_applied: false, total: HUF("158400") } },
        total_steps: [{ name: "frequency", factor: "1.03", after: HUF("487000") }] },
      tariff: { ref: "inv_tariff@1", title: "Business property tariff", currency: "HUF", factors: { claims: "Claims history", frequency: "Payment frequency" } },
      modules: { property: "Property cover" }, units: { "u-11": { level: "asset_group", named: { asset_group: "buildings" } } }, catalogue: CAT,
    };
    show("calculation", "rate", data, "rating@1", "Premium");
    const lines = await screen.findByRole("table", { name: "The premium's lines" });
    expect(lines.textContent).toContain("Claims history ×1.1");
    expect(lines.textContent).toContain("Property cover together");
    expect(screen.getByText("On the whole: Payment frequency ×1.03")).toBeTruthy();
    expect(document.querySelector(".ledger-total strong")?.textContent).toBe("487,000 HUF");
    expect(screen.getByText("487,000 HUF", { selector: ".status" }).className).toBe("status s-done");
  });
});

describe("the missing facts", () => {
  it("says what is missing and by when, and takes 'they will not come' only with a reason", async () => {
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue({} as CaseView);
    const data: MissingInfoData = { state: "running", missing: [{ unit_id: "u-1", fact: "accounting_method", title: "Accounting method" }],
      closes: "expired", days: 14, task: { status: "open", due_at: "2026-11-09T10:00:00+00:00", opened_at: "2026-10-26T10:00:00+00:00",
        closed_at: null, note: null, outcome: null } };
    show("missing_info", "missing", data, "missing_info@1", "Missing facts", "running");
    expect((await screen.findByText("1 missing")).className).toBe("status s-review");
    expect(screen.getByText("Accounting method").className).toBe("todo-text");
    fireEvent.click(screen.getByRole("button", { name: "The facts will not come" }));
    const give = screen.getAllByRole("button", { name: "The facts will not come" })[0];
    expect(give).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByRole("textbox", { name: "Why they will not come" }), { target: { value: "the client withdrew" } });
    fireEvent.click(give);
    await waitFor(() => expect(act).toHaveBeenCalledWith(CASE, "missing", "will_not_come", "the client withdrew"));
  });
});
