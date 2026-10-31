// 264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): the routing's documents to route
// are the one list - the selected ones are decided at once, and the list is read again after a decision. Synthetic
// attachments, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView } from "../../api";
import type { RoutingItem, RoutingView } from "./api";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { FilePlacement } from "./FilePlacement";
import { mockRouting } from "./routingItems.testutil";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const item = (file: string, state: number): RoutingItem => ({
  item_id: `id-${file}`, file, package: "wp-00000000000m", doc_type: "invoice_hu", tier: "approved", held: null, decision: null,
  decision_state: state, email: { subject: "June", sender: "billing@example.com", received_at: "2026-06-20T10:00:00", folder: "inbox" },
  placement: { routable: true, role: "incoming_invoices", role_title: "Incoming invoices", party_id: "p1", party: "Example Kft.",
    day: "2026-06-08", problem: null },
  proposal: { target: { id: "wp-00000000000t", name: "June incoming" }, others: [], new: null },
} as unknown as RoutingItem);
const view = (items: RoutingItem[]): RoutingView => ({ sources: [], items,
  counts: { attachments: items.length, routable: items.length, decided: 0, blocked: 0, clear: items.length, accepted: 0 } });

describe("the documents to route as the one list", () => {
  it("decides the selected ones at once and reads the list again after a decision", async () => {
    const items = [item("a.pdf", 1), item("b.pdf", 2)];
    const query = mockRouting(view(items));
    const reject = vi.spyOn(api, "routingReject").mockResolvedValue(view(items));
    const props = { caseId: "wp-00000000000r", page: {} as CaseView, onChanged: () => {} };
    const { rerender } = render(<FilePlacement {...props} element={{ type: "file_placement", step: "route", show: "decide", data: view(items) }} />);
    const table = await screen.findByRole("table", { name: "Documents to route" });
    for (const f of ["a.pdf", "b.pdf"]) await userEvent.click(within((await within(table).findByText(f)).closest("tr")!).getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Do not route (2)" }));
    await waitFor(() => expect(reject).toHaveBeenCalledWith("wp-00000000000r", ["id-a.pdf", "id-b.pdf"], { "id-a.pdf": 1, "id-b.pdf": 2 }));
    const asked = query.mock.calls.length;
    rerender(<FilePlacement {...props} element={{ type: "file_placement", step: "route", show: "decide", data: view([item("a.pdf", 3), item("b.pdf", 4)]) }} />);
    await waitFor(() => expect(query.mock.calls.length).toBeGreaterThan(asked));
  });

  it("has its words in Hungarian", () => {
    const hu = hungarian as Record<string, string>;
    for (const key of ["Decide", "Accept the proposals ({{n}})", "Do not route ({{n}})", "To decide", "Documents to route", "What holds it"]) {
      expect(hu[key], key).toBeTruthy();
      expect(hu[key]).not.toBe(key);
    }
  });
});
