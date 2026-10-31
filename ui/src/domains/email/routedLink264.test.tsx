// 264 (plan E, F5; the owner's decision of 2026-10-31): a routed document's batch leads to its Processing, instead of a
// sentence that says to start its run there. Synthetic data.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { CaseView } from "../../api";
import type { RoutingView } from "./api";
import { setLanguage } from "../../i18n";
import { FilePlacement } from "./FilePlacement";

beforeEach(async () => { await setLanguage("en"); });
afterEach(() => cleanup());

const VIEW = {
  sources: [],
  items: [{ item_id: "doc-1", file: "invoice.pdf", package: "wp-000000000001",
    decision: { decision: "accepted", target: "wp-000000000002", target_name: "Example Kft. · 2026-06 · Incoming invoices" } }],
  counts: {},
} as unknown as RoutingView;

describe("the routed documents", () => {
  it("lead to their batch's Processing", () => {
    render(<FilePlacement caseId="wp-000000000231" element={{ type: "file_placement", step: "route", show: "routed", data: VIEW }}
      page={{} as CaseView} onChanged={() => {}} />);
    const table = screen.getByRole("table", { name: "Routed documents" });
    expect(within(table).getByRole("link", { name: "To its Processing" }).getAttribute("href"))
      .toBe("#/workpackages/wp-000000000002/process");
    expect(screen.queryByText(/start it there/)).toBeNull();
  });
});
