// 261 (plan B, B2b; the owner's decisions of 2026-10-29): a case's page says, once a person opens it, what the case
// keeps from its start beside what a case started now would use, and leads to the settings new cases use; a case
// started before its settings were kept says so. Synthetic data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseSettings } from "../api";
import { setLanguage } from "../i18n";
import { CaseSettingsCard } from "./CaseSettings";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const CASE = "wp-00000000a265";
const KEPT: CaseSettings = {
  pack: "it_quote", kept: true,
  resources: [{ key: "price_list", label: "Price list", name: "Invented 2026", version: 2, now: { name: "Invented 2026", version: 3 } }],
  rules: [{ key: "quotes.draft.max_lines", what: "A quote holds at most this many lines", value: 320, origin: "installation", version: 1,
    now: 350, now_origin: "process" }],
};

describe("a case's settings (261 B2b)", () => {
  it("shows, once opened, what the case keeps beside what a case started now would use", async () => {
    const load = vi.spyOn(api, "caseSettings").mockResolvedValue(KEPT);
    render(<CaseSettingsCard caseId={CASE} pack="it_quote" />);
    expect(load).not.toHaveBeenCalled();  // nothing is asked until a person opens it
    expect(screen.getByRole("link", { name: "The settings new cases use →" }).getAttribute("href")).toBe("#/settings/processes/it_quote/values");
    fireEvent.click(screen.getByRole("button", { name: "Show the settings" }));
    const table = await screen.findByRole("table", { name: "The case's settings" });
    expect(load).toHaveBeenCalledWith(CASE);
    const list = within(table).getByText("Price list").closest("tr")!;
    expect(within(list).getByText("Invented 2026, version 2")).toBeTruthy();
    expect(within(list).getByText("Invented 2026, version 3")).toBeTruthy();
    const lines = within(table).getByText("A quote holds at most this many lines").closest("tr")!;
    expect(within(lines).getByText("320")).toBeTruthy();
    expect(within(lines).getByText("The installation's default, version 1")).toBeTruthy();
    expect(within(lines).getByText("350")).toBeTruthy();
  });

  it("says a case started before its settings were kept reads the files", async () => {
    vi.spyOn(api, "caseSettings").mockResolvedValue({ pack: "it_quote", kept: false, resources: [], rules: [] });
    render(<CaseSettingsCard caseId={CASE} pack="it_quote" />);
    fireEvent.click(screen.getByRole("button", { name: "Show the settings" }));
    await waitFor(() => expect(screen.getByText("The case started before its settings were kept: it reads the files and the active versions.")).toBeTruthy());
  });
});
