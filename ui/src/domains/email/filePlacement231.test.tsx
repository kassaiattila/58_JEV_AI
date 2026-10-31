// 231 (plan stage C, C1c; DECISIONS 231): the email routing on a routing case's tabs - the email packages it routes, the
// documents to decide with their proposals (accepted on the case's own package), and the cases started from the
// emails. Synthetic data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type DsPage } from "../../api";
import type { RoutingView } from "./api";
import { setLanguage } from "../../i18n";
import { StartedCases } from "../../elements/CaseElements";
import { FilePlacement } from "./FilePlacement";
import { mockRouting } from "./routingItems.testutil";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const VIEW = {
  sources: [{ id: "wp-000000000001", name: "Office mailbox" }],
  items: [{
    item_id: "doc-1", file: "invoice.pdf", package: "wp-000000000001", doc_type: "invoice_hu", tier: "done", held: null, decision: null,
    decision_state: 0, email: { subject: "About m1", sender: "billing@example.com", received_at: "2026-06-20T10:00:00", folder: "inbox" },
    placement: { routable: true, problem: null, note: null, role: "incoming_invoices", role_title: "Incoming invoices", party: "Example Kft.",
      party_id: "p1", day: "2026-06-08" },
    proposal: { target: null, others: [], new: { name: "Example Kft. · 2026-06 · Incoming invoices", party: "Example Kft.", period_start: "2026-06-01" } },
  }],
  counts: { attachments: 1, routable: 1, decided: 0, blocked: 0, clear: 1, accepted: 0 },
} as unknown as RoutingView;
const PAGE = {} as CaseView;
const element = (show: string) => ({ type: "file_placement", step: "route", show, data: VIEW });

describe("the email routing on a case's tabs (231 C1c)", () => {
  it("lists the email packages it routes", () => {
    render(<FilePlacement caseId="wp-000000000231" element={element("sources")} page={PAGE} onChanged={() => {}} />);
    expect(screen.getByRole("link", { name: "Office mailbox" }).getAttribute("href")).toBe("#/workpackages/wp-000000000001");
  });

  it("accepts the clear proposals on the case's own package", async () => {
    const accept = vi.spyOn(api, "routingAcceptClear").mockResolvedValue({} as never);
    const changed = vi.fn();
    mockRouting(VIEW);  // 264 (F6): the one list of the service
    render(<FilePlacement caseId="wp-000000000231" element={element("decide")} page={PAGE} onChanged={changed} />);
    const table = await screen.findByRole("table", { name: "Documents to route" });
    expect(await within(table).findByText("invoice.pdf")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Accept every clear proposal (1)" }));
    await waitFor(() => expect(accept).toHaveBeenCalledWith("wp-000000000231", { incoming_invoices: "Incoming invoices" }));
    await waitFor(() => expect(changed).toHaveBeenCalled());
  });

  it("lists the cases started from the emails, in the shared data table (261 B1f)", async () => {
    const started: DsPage = {
      dataset: { name: "started_cases", label: "Started cases", scope: ["case_id"], optional_scope: [] },
      columns: [{ key: "name", label: "Case", kind: "text", hidden: false, labels: null, link: "case" },
        { key: "process", label: "Process", kind: "enum", hidden: false, labels: { "IT quote": "IT quote" } },
        { key: "status", label: "State", kind: "enum", hidden: false, labels: { open: "Case open", closed: "Case closed" } }],
      rows: [{ _key: "wp-000000000196", _wp: "wp-000000000196", name: "IT quote: Example", process: "IT quote", status: "open" }],
      total: 1, matched: 1, offset: 0, limit: 50, facets: {},
    } as unknown as DsPage;
    const query = vi.spyOn(api, "datasetQuery").mockResolvedValue(started);
    render(<StartedCases caseId="wp-000000000231" element={{ type: "started_cases", step: null,
      data: { dataset: "started_cases", scope: { case_id: "wp-000000000231" } } }} page={PAGE} onChanged={() => {}} />);
    expect((await screen.findByRole("link", { name: "IT quote: Example" })).getAttribute("href")).toBe("#/cases/wp-000000000196");
    expect(screen.getByText("Case open")).toBeTruthy();
    expect(query.mock.calls[0][0]).toBe("started_cases");
    expect(query.mock.calls[0][1]).toEqual({ case_id: "wp-000000000231" });
  });
});
