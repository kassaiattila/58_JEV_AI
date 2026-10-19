// 181 (plan 170 L5; DECISIONS 181): the email routing package's routing stage: each document with its email, what it
// is, the proposal or why it cannot be placed, and a person's decision; every clear proposal at once. Synthetic names
// only; the local service is replaced by spies.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type RoutingItem, type RoutingView, type WorkpackageView } from "../../api";
import { setLanguage } from "../../i18n";
import { logicOf } from "../../logic/registry";
import { RoutingStages, routingStatus } from "./Routing";

const EMAIL = { item_id: "e1", subject: "June invoice", sender: "billing@example.com", received_at: "2026-06-20T10:00:00", folder: "inbox" };

function item(file: string, over: Partial<RoutingItem> = {}): RoutingItem {
  return {
    item_id: `id-${file}`, file, package: "wp-00000000000m", email: EMAIL, doc_type: "invoice_hu", tier: "approved",
    placement: { routable: true, role: "incoming_invoices", role_title: "Incoming invoices", party_id: "party-00000000000a",
      party: "Example Kft.", day: "2026-06-08", problem: null },
    proposal: { target: { id: "wp-00000000000t", name: "June incoming" }, others: [], new: null }, decision: null, ...over,
  };
}

function routing(items: RoutingItem[]): RoutingView {
  const routable = items.filter((i) => i.placement.routable);
  return { sources: [{ id: "wp-00000000000m", name: "Office mailbox" }], items,
    counts: { attachments: items.length, routable: routable.length, decided: routable.filter((i) => i.decision).length,
      blocked: routable.filter((i) => !i.decision && i.placement.problem).length,
      clear: routable.filter((i) => !i.decision && i.proposal).length,
      accepted: routable.filter((i) => i.decision?.decision === "accepted").length } };
}

function view(items: RoutingItem[]): WorkpackageView {
  return { workpackage: { id: "wp-00000000000r", name: "Routing", source_kind: "email_routing", status: "open", items: [] },
    routing: routing(items) } as unknown as WorkpackageView;
}

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("181 the email routing package", () => {
  it("is a logic pack of its own with three stages", () => {
    const v = view([item("invoice.pdf"), item("contract.pdf", { placement: { ...item("x").placement, routable: false, role: null } })]);
    expect(logicOf("email_routing")?.adds).toBe("nothing");
    expect(routingStatus(v)).toEqual({ process: "1 email package(s), 2 attachment(s)", review: "1 to decide", result: "0 routed" });
  });

  it("shows each document's proposal or blocker and accepts every clear one at once", async () => {
    const items = [
      item("invoice.pdf"),
      item("sold.pdf", { email: { ...EMAIL, folder: "sent" }, placement: { ...item("x").placement, role: "outgoing_invoices", role_title: "Outgoing invoices" },
        proposal: { target: null, others: [], new: { name: "Example Kft. · 2026-06 · Outgoing invoices", party_id: "party-00000000000a",
          period_start: "2026-06-01", period_end: "2026-06-30", role: "outgoing_invoices" } } }),
      item("odd.pdf", { placement: { ...item("x").placement, problem: "suspicious" }, proposal: null }),
      item("done.pdf", { proposal: null, decision: { decision: "accepted", target: "wp-00000000000t", target_name: "June incoming", made: 0,
        actor: "Synthetic reviewer", decided_at: "2026-10-20T10:00:00+00:00" }, held: true }),
    ];
    const acceptClear = vi.spyOn(api, "routingAcceptClear").mockResolvedValue(routing(items));
    const reject = vi.spyOn(api, "routingReject").mockResolvedValue(routing(items));
    const onChanged = vi.fn();
    render(<RoutingStages view={view(items)} stage="review" onChanged={onChanged} />);
    const table = screen.getByRole("table", { name: "Documents to route" });
    const row = (file: string) => within(table).getByText(file).closest("tr") as HTMLElement;
    expect(row("invoice.pdf").textContent).toContain("June incoming");
    expect(row("invoice.pdf").textContent).toContain("Incoming invoices · Example Kft. · 2026-06-08");
    expect(row("sold.pdf").textContent).toContain("sent · 2026-06-20");
    expect(row("sold.pdf").textContent).toContain("New package: Example Kft. · 2026-06 · Outgoing invoices");
    expect(row("odd.pdf").textContent).toContain("It came with a suspicious email");
    expect(within(row("odd.pdf")).queryByRole("button", { name: "Accept" })).toBeNull(); // a blocker: choose or do not route
    expect(row("done.pdf").textContent).toContain("added");
    const all = screen.getByRole("button", { name: "Accept every clear proposal (2)" });
    expect(all.className).toBe("primary");
    fireEvent.click(all);
    await waitFor(() => expect(acceptClear).toHaveBeenCalledWith("wp-00000000000r"));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    fireEvent.click(within(row("odd.pdf")).getByRole("button", { name: "Do not route" }));
    await waitFor(() => expect(reject).toHaveBeenCalledWith("wp-00000000000r", ["id-odd.pdf"]));
  });
});
