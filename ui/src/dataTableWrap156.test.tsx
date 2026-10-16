// 156: a name-like column (a file name, a path, an e-mail address) marks its cells, so only they may break inside a
// word; one long address cannot widen the whole table past the screen. Artificial data, no service.
import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, type DsColumn, type DsPage } from "./api";
import { DataTable } from "./components/DataTable";

afterEach(() => vi.restoreAllMocks());

const COLS: DsColumn[] = [
  { key: "subject", label: "Subject", kind: "text", hidden: false, labels: null },
  { key: "sender", label: "Sender", kind: "text", hidden: false, labels: null, wrap: "anywhere" },
];

it("only the cells of a name-like column may break inside a word", async () => {
  vi.spyOn(api, "datasetQuery").mockResolvedValue({
    dataset: { name: "emails", label: "Emails", scope: ["run_id"], optional_scope: [] }, columns: COLS,
    rows: [{ _key: "m1", subject: "Monthly statement", sender: "Billing <billing.department@example.invalid>" }],
    total: 1, matched: 1, offset: 0, limit: 100, facets: {},
  } as unknown as DsPage);
  render(<DataTable dataset="emails" scope={{ run_id: "run-1" }} label="Emails" />);
  const sender = (await screen.findByText(/billing\.department/)).closest("td") as HTMLElement;
  const subject = screen.getByText("Monthly statement").closest("td") as HTMLElement;
  expect(sender.dataset.wrap).toBe("anywhere");
  expect(subject.dataset.wrap).toBeUndefined();
});
