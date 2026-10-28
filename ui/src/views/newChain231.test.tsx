// 231 (stage U, U2c; the owner's decision of 2026-10-28: a chain is a multi-step process): a multi-step process starts
// from New case as any other. Its form asks the own party and the period once and each step's own documents: the
// invoices from a packet of the documents process's invented documents, the statements from a folder; it starts only
// once every step has them. Synthetic data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type ProcessRow } from "../api";
import { setLanguage } from "../i18n";
import { NewCase } from "./NewCase";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.location.hash = ""; });

const CASE = "wp-000000000c02";
const PARTY = "party-000000000001";
const MONTHLY: ProcessRow = {
  id: "monthly_reconciliation", title: "Monthly reconciliation", version: "1.0.0", scope: ["party", "period", "step_sources"],
  asks: ["party", "period", "step_sources"], package_kinds: [], manual: true, examples: false, missing_at_start: [],
  summary: "An own party's period in one case.",
  step_sources: [
    { step: "invoices", title: "Incoming invoices", pack: "documents", process: "Documents", source_kinds: ["folder", "files"], examples: true },
    { step: "statements", title: "Bank statements", pack: "bank_statements", process: "Bank statements", source_kinds: ["folder", "files"], examples: false },
  ],
};

describe("a multi-step process's form (231 U2c)", () => {
  it("asks each step's own documents and starts the case with them", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [MONTHLY] });
    const examples = vi.spyOn(api, "processExamples").mockResolvedValue({ sets: [], packets: [
      { id: "own_party_invoices", title: "The invented consultancy's invoices", documents: 4 }] });
    vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
    vi.spyOn(api, "parties").mockResolvedValue({ parties: [{ id: PARTY, name: "Example Party Kft.", identities: [] }] } as never);
    const files = vi.spyOn(api, "examplePacketFiles").mockResolvedValue({ files: ["C:\\store\\examples\\inv-1.pdf"] });
    const start = vi.spyOn(api, "startCase").mockResolvedValue({ case_id: CASE });
    render(<NewCase pack="monthly_reconciliation" />);
    const form = await screen.findByRole("form", { name: "Monthly reconciliation" });
    fireEvent.change(within(form).getByLabelText("Own party"), { target: { value: PARTY } });
    fireEvent.change(within(form).getByLabelText("Period from"), { target: { value: "2026-03-01" } });
    fireEvent.change(within(form).getByLabelText("to"), { target: { value: "2026-06-30" } });
    const invoices = within(form).getByRole("group", { name: "Incoming invoices · Documents" });
    const statements = within(form).getByRole("group", { name: "Bank statements · Bank statements" });
    expect(examples).toHaveBeenCalledWith("documents");  // only the process with invented documents is asked
    fireEvent.click(await within(invoices).findByRole("radio", { name: "Example documents" }));
    fireEvent.change(within(invoices).getByLabelText("The packet of invented documents"), { target: { value: "own_party_invoices" } });
    expect(within(statements).queryByRole("radio", { name: "Example documents" })).toBeNull();
    const create = within(form).getByRole("button", { name: "Create" }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);  // the statements' folder is still missing
    fireEvent.change(within(statements).getByLabelText("The folder's full path"), { target: { value: "D:\\Invented\\statements" } });
    expect(create.disabled).toBe(false);
    fireEvent.click(create);
    await waitFor(() => expect(start).toHaveBeenCalled());
    expect(files).toHaveBeenCalledWith("documents", "own_party_invoices");
    expect(start).toHaveBeenCalledWith({
      pack: "monthly_reconciliation", name: "Monthly reconciliation · Example Party Kft. · 2026-03-01 – 2026-06-30",
      party_id: PARTY, period_start: "2026-03-01", period_end: "2026-06-30",
      step_sources: { invoices: { kind: "files", files: ["C:\\store\\examples\\inv-1.pdf"] },
                      statements: { kind: "folder", folder: "D:\\Invented\\statements", recursive: false } } });
    await waitFor(() => expect(window.location.hash).toBe(`#/cases/${CASE}`));
  });
});
