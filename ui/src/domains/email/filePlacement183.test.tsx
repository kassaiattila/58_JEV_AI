// 183 (DECISIONS 183, after the first real trial): an incoming invoice in a sent email is proposed with a note; an
// attachment that was read but has no data has a blocker of its own; another kind is listed with its type's name.
// Synthetic names only; the local service is not called.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { setActor, type CaseView } from "../../api";
import type { RoutingItem, RoutingView } from "./api";
import { setLanguage } from "../../i18n";
import { docTypeLabel } from "../../labels";
import { FilePlacement } from "./FilePlacement";

const EMAIL = { item_id: "e1", subject: "Fwd: June invoice", sender: "office@example.com", received_at: "2026-06-20T10:00:00", folder: "sent" };

function item(file: string, over: Partial<RoutingItem> = {}): RoutingItem {
  return {
    item_id: `id-${file}`, file, package: "wp-00000000000m", email: EMAIL, doc_type: "invoice_hu", tier: "trial",
    placement: { routable: true, role: "incoming_invoices", role_title: "Incoming invoices", party_id: "party-00000000000a",
      party: "Example Kft.", day: "2026-06-08", problem: null, note: null },
    proposal: { target: { id: "wp-00000000000t", name: "June incoming" }, others: [], new: null }, decision: null, ...over,
  };
}


function routing(items: RoutingItem[]): RoutingView {
  const routable = items.filter((i) => i.placement.routable);
  return { sources: [{ id: "wp-00000000000m", name: "Office mailbox" }], items,
    counts: { attachments: items.length, routable: routable.length, decided: 0,
      blocked: routable.filter((i) => i.placement.problem).length, clear: routable.filter((i) => i.proposal).length, accepted: 0 } };
}

const PAGE = {} as CaseView;
const element = (items: RoutingItem[]) => ({ type: "file_placement", step: "route", show: "decide", data: routing(items) });

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); });

describe("183 the email routing after its first real trial", () => {
  it("proposes a forwarded incoming invoice with a note, names the no-data blocker and lists another kind by its type", () => {
    const items = [
      item("forwarded.pdf", { placement: { ...item("x").placement, note: "sent_incoming" } }),
      item("scanned.pdf", { placement: { ...item("x").placement, role: null, role_title: null, party_id: null, party: null, day: null,
        problem: "no_data" }, proposal: null }),
      item("return.pdf", { doc_type: "tax_return", placement: { ...item("x").placement, routable: false, role: null, role_title: null,
        party_id: null, party: null, day: null }, proposal: null }),
    ];
    render(<FilePlacement caseId="wp-00000000000r" element={element(items)} page={PAGE} onChanged={() => undefined} />);
    const table = screen.getByRole("table", { name: "Documents to route" });
    const row = (file: string) => within(table).getByText(file).closest("tr") as HTMLElement;
    expect(row("forwarded.pdf").textContent).toContain("June incoming");
    expect(row("forwarded.pdf").textContent).toContain("An incoming invoice in a sent email");
    expect(within(row("forwarded.pdf")).getByRole("button", { name: "Accept" })).toBeTruthy();
    expect(row("scanned.pdf").textContent).toContain("Read, but it has no data: see its to-dos in its email batch");
    expect(within(row("scanned.pdf")).queryByRole("button", { name: "Accept" })).toBeNull();
    expect(screen.getByRole("button", { name: "Accept every clear proposal (1)" })).toBeTruthy();
    expect(screen.getByText("Attachments of another kind (1)").closest("details")?.textContent).toContain(`return.pdf · ${docTypeLabel("tax_return")}`);
  });
});
