// 231 (stage U, U3e; the owner's decisions of 2026-10-28): the Settings menu in three groups - the processes, the
// shared library every process chooses from, and the system - each under its name; the own parties stand among the
// partners with the role "own", each leading to its own register, where it is still edited. 263 (E1; the owner's
// decisions of 2026-10-30): the menu is the table of contents in the left panel, a group a branch that opens and closes;
// the partners are the one list, each row opening its page. Invented data, a mocked service.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor } from "../../api";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { Settings } from "../Settings";
import { PartnersPanel } from "./PartnersPanel";
import { listPage } from "./listPage.testutil";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); localStorage.clear(); sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const AT = "2026-10-28T09:00:00+00:00";

describe("the Settings menu in three groups (231 U3e; 263 E1: the table of contents)", () => {
  it("names each group and holds its sections in it", () => {
    vi.spyOn(api, "users").mockResolvedValue({ users: [] } as never);
    render(<Settings section="users" />);
    const nav = screen.getByRole("navigation", { name: "Settings" });
    const groups = within(nav).getAllByRole("button").filter((b) => b.classList.contains("nav-group")).map((b) => b.textContent);
    expect(groups).toEqual(["Processes", "Shared library", "System"]);
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "All processes", "Partners", "Own parties", "Products", "Price lists", "Output templates", "Letter frames",
      "Users", "Appearance", "Language", "Work folders", "Mailboxes", "Processing", "Defaults", "Operations"]);
    expect(within(nav).getByRole("link", { name: "Users" }).getAttribute("aria-current")).toBe("page");
    // the page's title is the section's, Settings the crumb above it
    expect(screen.getByRole("heading", { level: 1, name: "Users" })).toBeTruthy();
    expect(within(screen.getByRole("navigation", { name: "Location" })).getByRole("link", { name: "Settings" })).toBeTruthy();
  });

  it("names the processes' overview All processes in the menu and on the page", () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [{ id: "invented", title: "Invented process", version: "1.0.0" }] } as never);
    vi.spyOn(api, "datasetQuery").mockResolvedValue(listPage("settings_processes", [], []));
    render(<Settings section="processes" />);
    expect(screen.getByRole("heading", { level: 1, name: "All processes" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "All processes" }).getAttribute("aria-current")).toBe("page");
  });

  it("lists the own parties among the partners with the role own, each leading to its register", async () => {
    vi.spyOn(api, "datasetQuery").mockResolvedValue(listPage("settings_partners", [
      { key: "name", label: "Name", kind: "text", hidden: false, labels: null, link: "settings", section: "partners" },
      { key: "kind", label: "Kind", kind: "enum", hidden: false, labels: { partner: "Partner", own: "Own party" }, group: true },
      { key: "tax_number", label: "Tax number", kind: "id", hidden: false, labels: null },
    ], [
      { _key: "own:party-000000000001", _settings: ["parties"], name: "Example Own Kft.", kind: "own", tax_number: "12121216-2-42", changed_at: AT },
      { _key: "partner-000000000001", name: "Invented Buyer Ltd", kind: "partner", tax_number: null, changed_at: AT },
    ]));
    render(<PartnersPanel />);
    const own = await screen.findByRole("link", { name: "Example Own Kft." });
    expect(own.getAttribute("href")).toBe("#/settings/parties");
    expect(within(own.closest("tr")!).getByText("Own party")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Invented Buyer Ltd" }).getAttribute("href")).toBe("#/settings/partners/partner-000000000001");
    expect(screen.getByRole("link", { name: "Suggestions from the data →" }).getAttribute("href")).toBe("#/settings/partners/proposals");
  });

  it("has its words in Hungarian", () => {
    const hu = hungarian as Record<string, string>;
    for (const key of ["Shared library", "System", "Operations", "All processes", "Contents", "Hide", "Pin", "Group by"]) {
      expect(hu[key]).toBeTruthy();
    }
  });
});
