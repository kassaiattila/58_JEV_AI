// 264 (plan E, F5; the owner's decision of 2026-10-31): a process's opened setting is in the page's address
// (`?open=rules:<key>`), so a reload or a link sent on opens it again; closing it takes it out. Synthetic data, a
// mocked service.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type ProcessSettings } from "../../api";
import { setLanguage } from "../../i18n";
import { ProcessSettingsPanel } from "./ProcessSettingsPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); window.location.hash = ""; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const PAGE = {
  pack: { id: "invented_quote", title: "Invented quote", version: "1.0.0" },
  resources: [],
  rules: [{ key: "quotes.draft.max_lines", file: "quotes", path: "draft.max_lines", what: "A quote holds at most this many lines",
    kind: "int", least: 1, most: 1000, options: [], steps: ["compose"], file_value: 300, value: 300, own: false, versions: [] }],
  partners: [], policy: { activation: "editor", owners: [] },
  description: { summary: "", outputs: [], goldens: [], examples: false, intake: [], steps: [] },
} as unknown as ProcessSettings;

describe("a process's opened setting", () => {
  it("is put in the address when opened and taken out when closed", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [PAGE.pack] });
    vi.spyOn(api, "processSettings").mockResolvedValue(PAGE);
    render(<ProcessSettingsPanel pack="invented_quote" tab="values" />);
    const name = await screen.findByRole("button", { name: "A quote holds at most this many lines" });
    fireEvent.click(name);
    expect(window.location.hash).toBe("#/settings/processes/invented_quote/values?open=rules%3Aquotes.draft.max_lines");
    fireEvent.click(name);
    expect(window.location.hash).toBe("#/settings/processes/invented_quote/values");
  });

  it("opens again from the address", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [PAGE.pack] });
    vi.spyOn(api, "processSettings").mockResolvedValue(PAGE);
    render(<ProcessSettingsPanel pack="invented_quote" tab="values" open="rules:quotes.draft.max_lines" />);
    expect(await screen.findByRole("region", { name: "A quote holds at most this many lines" })).toBeTruthy();
  });
});
