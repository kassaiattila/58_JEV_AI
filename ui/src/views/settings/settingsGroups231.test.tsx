// 231 (stage U, U3e; the owner's decisions of 2026-10-28): the Settings menu in three groups - the processes, the
// shared library every process chooses from, and the system - each under its name; the own parties stand among the
// partners with the role "own", each leading to its own register, where it is still edited. Invented data, a mocked
// service.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type PartnerRoles } from "../../api";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { routeHash } from "../../route";
import { Settings } from "../Settings";
import { PartnersPanel } from "./PartnersPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const ROLES: PartnerRoles = { customer: { label: "Customer", what: "Asks for a quote" } };
const AT = "2026-10-28T09:00:00+00:00";

describe("the Settings menu in three groups (231 U3e)", () => {
  it("names each group and holds its sections in it", () => {
    vi.spyOn(api, "users").mockResolvedValue({ users: [] } as never);
    render(<Settings section="users" />);
    const nav = screen.getByRole("navigation", { name: "Settings" });
    const items = (name: string) => within(within(nav).getByRole("group", { name })).getAllByRole("link").map((a) => a.textContent);
    expect(within(nav).getAllByRole("group").map((g) => g.getAttribute("aria-labelledby"))).toHaveLength(3);
    expect(items("Processes")).toEqual(["All processes"]);
    expect(items("Shared library")).toEqual(["Partners", "Own parties", "Products", "Price lists", "Output templates", "Letter frames"]);
    expect(items("System")).toEqual(["Users", "Appearance", "Language", "Work folders", "Mailboxes", "Processing", "Defaults", "Operations"]);
    expect(within(nav).getByRole("link", { name: "Users" }).getAttribute("aria-current")).toBe("page");
  });

  it("names the processes' overview All processes in the menu", () => {
    render(<Settings section="processes" />);
    expect(screen.getByRole("heading", { level: 2, name: "Processes" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "All processes" }).getAttribute("aria-current")).toBe("page");
  });

  it("lists the own parties among the partners with the role own, each leading to its register", async () => {
    vi.spyOn(api, "partners").mockResolvedValue({
      roles: ROLES,
      partners: [{ partner_id: "partner-000000000001", name: "Invented Buyer Ltd", tax_number: null, email: "buyer@example.com", phone: null,
        address: null, note: null, roles: ["customer"], version: 1, retired: false, changed_at: AT }],
      own: [{ party_id: "party-000000000001", name: "Example Own Kft.", tax_number: "12121216-2-42", changed_at: AT }],
    });
    vi.spyOn(api, "partnerSuggestions").mockResolvedValue({ suggestions: [] });
    vi.spyOn(api, "usedBy").mockResolvedValue({ used_by: {} });
    render(<PartnersPanel />);
    const own = await screen.findByRole("link", { name: "Example Own Kft." });
    expect(own.getAttribute("href")).toBe(routeHash({ view: "settings", section: "parties" }));
    const row = own.closest("tr")!;
    expect(within(row).getByText("Own party")).toBeTruthy();
    expect(within(row).getByText("12121216-2-42")).toBeTruthy();
    const names = screen.getAllByRole("row").slice(1).map((r) => r.querySelector("td")?.textContent);
    expect(names).toEqual(["Example Own Kft.", "Invented Buyer Ltd"]);  // one list, by name
    expect(screen.getByText("An own party is edited under Own parties.")).toBeTruthy();
    expect(within(screen.getByLabelText("Role")).getByRole("option", { name: "Own party" }).getAttribute("value")).toBe("own");
  });

  it("has its words in Hungarian", () => {
    const hu = hungarian as Record<string, string>;
    for (const key of ["Shared library", "System", "Operations", "All processes", "An own party is edited under Own parties."]) {
      expect(hu[key]).toBeTruthy();
    }
  });
});
