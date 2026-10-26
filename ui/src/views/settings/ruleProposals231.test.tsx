// 231 (stage D, D-c7g): rule proposals in Settings › Products. A run is started from a document version and a file,
// by the free stand-in or by GPT within a budget its button shows; a run lists its proposals with the code's check, JEV's
// mark and the decision; a proposal opens with its decision table, its findings and where its numbers stand; a person
// accepts it once the numbers the document does not print are confirmed, or rejects it with a reason; a blocked one
// cannot be accepted. Invented data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type ProductRegistry, type Rule, type RuleProposal, type RuleProposalRun } from "../../api";
import { setLanguage } from "../../i18n";
import { ProposalsView } from "./ProposalsView";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const AT = "2026-10-26T09:00:00+00:00";
const DOC = { kind: "general" as const, title: "Invented general conditions (GC-2026)", valid_from: "2026-01-01", valid_to: null,
  references: [], sections: [{ clause: "3.2", page: 2, title: "Claims history" }] };
const REGISTRY: ProductRegistry = {
  products: [], rules: [], tariffs: [],
  documents: [{ ident: "invented_general", name: DOC.title, active: 1, retired: false, versions: [{ ident: "invented_general", version: 1,
    ref: "invented_general@1", state: "active", name: DOC.title, content: DOC, made_by: "a", made_at: AT, activated_by: "b",
    activated_at: AT, retired_by: null, retired_at: null }] }],
  catalogues: { property: { id: "property", version: "1.2.0", levels: ["holder"], labels: {},
    facts: { claims_5y_count: { type: "count", level: "holder", title: "Claims in the last five years", unit: null, currency: null, options: null } },
    outcomes: { premium_factor: { type: "decimal", title: "Premium factor", combine: "one", unit: null, currency: null, options: null } } } },
};
const RULE: Rule = { catalogue: "property", kind: "premium_factor", title: "Claims factor", level: "holder", modules: [],
  facts: ["claims_5y_count"], applies_at: ["quote"],
  table: { hit: "first", rows: [{ when: { claims_5y_count: { eq: 0 } }, then: { premium_factor: "0.9" } }, { when: {}, then: { premium_factor: "1.0" } }] },
  source: { document: "invented_general@1", page: 2, clause: "3.2", quote: "a claim-free history earns a discount of 10%" } };
const proposal = (id: number, readiness: RuleProposal["readiness"], extra: Partial<RuleProposal> = {}): RuleProposal => ({
  id, run_id: "rpr-0000000001", n: id, pages: [1, 2, 3], title: `Proposal ${id}`, kind: "premium_factor", page: 2, clause: "3.2",
  rule: RULE, problem: null, findings: [], numbers: [{ value: "0.9", where: "derived", page: null }], support: null, readiness,
  state: "proposed", correction: null, confirmed: [], reason: null, rule_ref: null, decided_by: null, decided_at: null,
  decision_state: 0, ...extra });
const RUN: RuleProposalRun = {
  run_id: "rpr-0000000001", document_ref: "invented_general@1", file: "invented_general.pdf", file_sha256: "x", catalogue: "property",
  product: null, proposer: "stand_in:golden_products", stand_in: true, verify: false, state: "done", limits: {}, usage: null,
  page_count: 4, skipped: { "4": "Internal" }, ocr_pages: [], text_source: "pdf", error: null, requested_by: "a", requested_at: AT,
  finished_at: AT, counts: { proposed: 3 },
  proposals: [
    proposal(1, "ready"),
    proposal(2, "confirm", { numbers: [{ value: "0", where: "not_found", page: null }, { value: "0.9", where: "derived", page: null }],
      findings: [{ code: "number", severity: "attention", text: { text: "0 is not in the document: a person confirms it",
        template: "{{value}} is not in the document: a person confirms it", params: { value: "0" }, within: null } }] }),
    proposal(3, "blocked", { findings: [{ code: "quote", severity: "blocking", text: { text: "its quote is not in the document",
      template: "its quote is not in the document", params: {}, within: null } }] }),
  ],
};

function mockRuns() {
  vi.spyOn(api, "ruleProposalRuns").mockResolvedValue({ runs: [RUN], stand_ins: ["golden_products"] });
  vi.spyOn(api, "ruleProposalRun").mockResolvedValue(RUN);
}

async function openRun() {
  render(<ProposalsView registry={REGISTRY} onChanged={() => undefined} />);
  fireEvent.click(await screen.findByRole("button", { name: "Invented general conditions (GC-2026)" }));
  return screen.findByRole("region", { name: "Proposal run" });
}

describe("rule proposals (231 D-c7g)", () => {
  it("starts a stand-in run from a document version and a file, free; a GPT run shows its cap", async () => {
    mockRuns();
    const start = vi.spyOn(api, "startRuleProposals").mockResolvedValue(RUN);
    render(<ProposalsView registry={REGISTRY} onChanged={() => undefined} />);
    const card = await screen.findByRole("region", { name: "Propose rules from a document" });
    const go = within(card).getByRole("button", { name: "Propose rules" }) as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    fireEvent.click(within(card).getByRole("button", { name: "The document version the rules cite" }));
    fireEvent.click(await screen.findByRole("option", { name: /Invented general conditions/ }));
    fireEvent.change(within(card).getByRole("textbox", { name: "The document's file (.pdf)" }), { target: { value: "C:/x/general.pdf" } });
    expect(go.disabled).toBe(false);
    expect(go.className).toBe("primary");
    fireEvent.click(within(card).getByRole("radio", { name: "GPT, within a budget" }));
    expect((within(card).getByRole("button", { name: /Propose rules/ }) as HTMLButtonElement).disabled).toBe(true);  // no budget yet
    fireEvent.change(within(card).getByRole("textbox", { name: "OpenAI budget (USD)" }), { target: { value: "0,40" } });
    expect(within(card).getByRole("button", { name: /Propose rules/ }).textContent).toContain("≤");
    fireEvent.click(within(card).getByRole("radio", { name: /Stand-in/ }));
    fireEvent.click(within(card).getByRole("button", { name: "Propose rules" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith({ document: "invented_general@1", path: "C:/x/general.pdf", catalogue: "property",
      product: null, proposer: "stand_in:golden_products", limits: {}, verify: false }));
  });

  it("lists a run's proposals with the code's check and the pages its marking left out", async () => {
    mockRuns();
    const card = await openRun();
    expect(within(card).getByText("Left out by their marking (never sent): 4 (Internal)")).toBeTruthy();
    const rows = within(within(card).getByRole("table", { name: "Proposals" })).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[4].textContent)).toEqual(["Ready", "Numbers to confirm", "Blocked"]);
  });

  it("accepts a proposal once the numbers the document does not print are confirmed", async () => {
    mockRuns();
    const accept = vi.spyOn(api, "acceptRuleProposal").mockResolvedValue(RUN.proposals![1]);
    const card = await openRun();
    fireEvent.click(within(card).getByRole("button", { name: "Proposal 2" }));
    const detail = within(card).getByRole("group", { name: "Proposal 2" });
    expect(within(detail).getByRole("list", { name: "What to look at" }).textContent).toBe("0 is not in the document: a person confirms it");
    const button = within(detail).getByRole("button", { name: "Accept as a draft rule" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(within(detail).getByRole("checkbox", { name: /0/ }));
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    fireEvent.click(within(detail).getByRole("button", { name: "Sure? Click again" }));
    await waitFor(() => expect(accept).toHaveBeenCalledWith(2, 0, ["0"]));
  });

  it("keeps a blocked proposal from being accepted and rejects one only with a reason", async () => {
    mockRuns();
    const reject = vi.spyOn(api, "rejectRuleProposal").mockResolvedValue(RUN.proposals![2]);
    const card = await openRun();
    fireEvent.click(within(card).getByRole("button", { name: "Proposal 3" }));
    const detail = within(card).getByRole("group", { name: "Proposal 3" });
    expect(within(detail).getByRole("list", { name: "What blocks it" }).textContent).toBe("its quote is not in the document");
    expect((within(detail).getByRole("button", { name: "Accept as a draft rule" }) as HTMLButtonElement).disabled).toBe(true);
    const no = within(detail).getByRole("button", { name: "Reject" }) as HTMLButtonElement;
    expect(no.disabled).toBe(true);
    fireEvent.change(within(detail).getByRole("textbox", { name: "Reason for rejecting" }), { target: { value: "not a rule" } });
    fireEvent.click(no);
    fireEvent.click(within(detail).getByRole("button", { name: "Sure? Click again" }));
    await waitFor(() => expect(reject).toHaveBeenCalledWith(3, 0, "not a rule"));
  });
});
