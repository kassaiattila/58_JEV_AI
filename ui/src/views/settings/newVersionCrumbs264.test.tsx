// 264 (plan E, F5; the owner's decision of 2026-10-31): a new version's page has the thing it is a version of among its
// crumbs - Settings › Shared library › Output templates › Board report - and is titled "New version" (until now the
// crumbs stopped at the list and the title said "New version of Board report"). Synthetic data, a mocked service.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type OutputTemplatesListing } from "../../api";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { Settings } from "../Settings";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); localStorage.clear(); sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const LISTING = {
  templates: [{ template: "tpl-0123456789", output: "package_result", name: "Board report", active: 1, retired: false, versions: [] }],
  outputs: { package_result: { output: "package_result", what: "", format: "xlsx", markers: [] } },
} as unknown as OutputTemplatesListing;

describe("a new version's page", () => {
  it("names the thing it is a version of among its crumbs", async () => {
    vi.spyOn(api, "outputTemplates").mockResolvedValue(LISTING);
    render(<Settings section="outputs" item="tpl-0123456789" tab="upload" />);
    expect(await screen.findByRole("heading", { level: 1, name: "New version" })).toBeTruthy();
    const crumbs = screen.getByRole("navigation", { name: "Location" });
    expect(within(crumbs).getByRole("link", { name: "Board report" }).getAttribute("href")).toBe("#/settings/outputs/tpl-0123456789");
    expect(within(crumbs).getByRole("link", { name: "Output templates" })).toBeTruthy();
  });

  it("has its words in Hungarian", () => {
    expect((hungarian as Record<string, string>)["New version"]).toBeTruthy();
  });
});
