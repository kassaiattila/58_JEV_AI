// 191 (plan F-quote-package B2, DECISIONS 191): Settings › Price lists - the upload with the check's problems by row,
// a list's versions with their state and what made them, a version's items and its rules, which the owner decided are
// set on the settings page (saving makes a new draft version with the same items). The local service is replaced by
// spies; invented names, items and paths only.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setActor } from "../../api";
import type { PriceList, PriceListCheck, PriceListDetail, PriceListsListing, PriceListVersion } from "./api";
import { setLanguage, t } from "../../i18n";
import { settingsSections } from "../../logic/settingsSections";
import { priceIssueText, PriceListsPanel } from "./PriceListsPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const CHECK: PriceListCheck = { ok: true, problems: [], warnings: [], sheet: "Prices", columns: {}, items: 2, categories: ["hardware"] };

function version(over: Partial<PriceListVersion> = {}): PriceListVersion {
  return {
    price_list: "pl-0123456789", name: "Invented 2026", version: 1, state: "draft", change: "upload", based_on: null,
    currency: "HUF", vat_percent: "27", fingerprint: "f".repeat(64), file_name: "prices.xlsx", sha256: "0".repeat(64),
    made_by: "Synthetic reviewer", made_at: "2026-10-21T10:00:00+00:00", activated_by: null, activated_at: null,
    retired_by: null, retired_at: null, items: 2, discounts: [], check: CHECK, ...over,
  };
}

const list = (versions: PriceListVersion[]): PriceList => ({
  price_list: "pl-0123456789", name: "Invented 2026", active: versions.find((v) => v.state === "active")?.version ?? null,
  retired: false, versions,
});

function listing(lists: PriceList[]): PriceListsListing {
  const col = (required: boolean, headers: string[]) => ({ required, headers });
  return {
    price_lists: lists, currencies: ["HUF", "EUR"], currency: "HUF", vat_percent: "27",
    columns: { sku: col(true, ["item code"]), name: col(true, ["name"]), unit: col(true, ["unit"]),
               unit_price: col(true, ["unit price"]), category: col(false, ["category"]) },
  };
}

function detail(over: Partial<PriceListDetail> = {}): PriceListDetail {
  return {
    ...version({ state: "active" }), categories: ["hardware"],
    item_rows: [
      { sku: "HW-1", name: "Invented laptop", unit: "pc", unit_price: "489000", category: "hardware" },
      { sku: "SV-1", name: "Invented support hour", unit: "hour", unit_price: "15000.5", category: null },
    ], ...over,
  };
}

describe("Settings › Price lists (191)", () => {
  it("is a settings section with an English label and hint", () => {
    expect(settingsSections().map((x) => x.key)).toContain("prices");
    const s = settingsSections().find((x) => x.key === "prices")!;
    expect(t(s.label)).toBe("Price lists");
    expect(t(s.hint)).toBe(s.hint);
  });

  it("names every problem of a refused file with its row, and stores nothing", async () => {
    vi.spyOn(api, "priceLists").mockResolvedValue(listing([]));
    const check: PriceListCheck = { ...CHECK, ok: false, items: 0, categories: [], problems: [
      { code: "missing_column", where: "", detail: "unit" },
      { code: "duplicate_sku", where: "Prices!3", detail: "HW-1" },
    ] };
    const upload = vi.spyOn(api, "uploadPriceList").mockRejectedValue(new ApiError(422, "price_list_refused", "refused", [], {}, check));
    render(<PriceListsPanel item="new" />);  // 263: the upload's own page
    const button = await screen.findByRole("button", { name: "Upload and check" });
    expect(button).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Invented 2026" } });
    fireEvent.change(screen.getByLabelText("The price list's full path (.xlsx or .csv)"), { target: { value: "D:\\Invented\\prices.xlsx" } });
    fireEvent.click(button);
    const alert = await screen.findByRole("alert");
    expect(upload).toHaveBeenCalledWith({ name: "Invented 2026", path: "D:\\Invented\\prices.xlsx", currency: "HUF", vat_percent: "27" });
    expect(alert.textContent).toContain("The price list was not stored: the check found 2 problem(s).");
    expect(alert.textContent).toContain(priceIssueText("missing_column"));
    expect(alert.textContent).toContain("Unit"); // the missing column by its name, not its key
    expect(alert.textContent).toContain("Prices, row 3");
    expect(alert.textContent).toContain(priceIssueText("duplicate_sku"));
  });

  it("lists the versions with their state and what made them, and opens one with its items", async () => {
    vi.spyOn(api, "priceLists").mockResolvedValue(listing([list([
      version({ version: 2, state: "draft", change: "settings", based_on: 1, discounts: [{ category: "hardware", min_quantity: "10", percent: "5" }] }),
      version({ state: "active" }),
    ])]));
    const one = vi.spyOn(api, "priceListVersion").mockResolvedValue(detail());
    const { rerender } = render(<PriceListsPanel item="pl-0123456789" />);  // 263: the list's own page
    await screen.findByText(/active: version 1/);
    const rows = within(document.querySelector(".price-table") as HTMLElement).getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("Draft").className).toContain("s-trial");
    expect(within(rows[0]).getByText("settings, from version 1")).toBeTruthy();
    expect(within(rows[1]).getByText("Active").className).toContain("s-done");
    expect(within(rows[0]).getByRole("button", { name: "Make active" })).toBeTruthy();
    expect(within(rows[1]).getByRole("button", { name: "Retire" })).toBeTruthy();
    expect(within(rows[1]).getByRole("link", { name: "Open version 1" }).getAttribute("href")).toBe("#/settings/prices/pl-0123456789?open=1");
    rerender(<PriceListsPanel item="pl-0123456789" open="1" />);  // the version opens under its own row
    await screen.findByText("Invented laptop");
    expect(one).toHaveBeenCalledWith("pl-0123456789", 1);
    expect(screen.getByRole("link", { name: "Open version 1" }).getAttribute("aria-expanded")).toBe("true");
    const items = document.querySelector(".price-items-table") as HTMLElement;
    expect(within(items).getByText("489,000.00").className).toContain("tnum"); // amounts in tabular figures, grouped
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "support" } });
    expect(within(items).queryByText("Invented laptop")).toBeNull();
    expect(screen.getByRole("link", { name: "The uploaded file" }).getAttribute("href")).toBe("/api/price-lists/pl-0123456789/versions/1/file");
  });

  it("saves a new rule as a new draft version; the save is a disabled secondary button until something changed", async () => {
    vi.spyOn(api, "priceLists").mockResolvedValue(listing([list([version({ state: "active" })])]));
    vi.spyOn(api, "priceListVersion").mockResolvedValue(detail());
    const save = vi.spyOn(api, "changePriceListSettings").mockResolvedValue(version({ version: 2 }));
    render(<PriceListsPanel item="pl-0123456789" open="1" />);
    const button = await screen.findByRole("button", { name: "Save as a new version" });
    expect(button).toHaveProperty("disabled", true);
    expect(button.className).toContain("secondary");
    expect(screen.getByText("No rule: every item costs its unit price, whatever the quantity.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add a rule" }));
    fireEvent.change(screen.getByLabelText("From quantity, rule 1"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Discount, rule 1"), { target: { value: "2,5" } });
    expect(button).toHaveProperty("disabled", false);
    expect(button.className).toContain("primary");
    fireEvent.click(button);
    await waitFor(() => expect(save).toHaveBeenCalledWith("pl-0123456789", 1, {
      discounts: [{ category: "hardware", min_quantity: "10", percent: "2,5" }], currency: "HUF", vat_percent: "27",
    }));
    await waitFor(() => expect(window.location.hash).toBe("#/settings/prices/pl-0123456789?open=2"));  // the new draft opens
  });

  it("names a refused rule by its number", async () => {
    vi.spyOn(api, "priceLists").mockResolvedValue(listing([list([version({ state: "active" })])]));
    vi.spyOn(api, "priceListVersion").mockResolvedValue(detail({ discounts: [{ category: "hardware", min_quantity: "10", percent: "5" }] }));
    const check: PriceListCheck = { ...CHECK, ok: false, problems: [{ code: "percent_out_of_range", where: "rule 1", detail: "" }] };
    vi.spyOn(api, "changePriceListSettings").mockRejectedValue(new ApiError(422, "price_list_refused", "refused", [], {}, check));
    render(<PriceListsPanel item="pl-0123456789" open="1" />);
    const percent = await screen.findByLabelText("Discount, rule 1");
    expect((percent as HTMLInputElement).value).toBe("5");
    fireEvent.change(percent, { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: "Save as a new version" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("rule 1");
    expect(alert.textContent).toContain(priceIssueText("percent_out_of_range"));
  });

  it("says a list without categories can have no volume discount", async () => {
    vi.spyOn(api, "priceLists").mockResolvedValue(listing([list([version({ state: "active" })])]));
    vi.spyOn(api, "priceListVersion").mockResolvedValue(detail({ categories: [] }));
    render(<PriceListsPanel item="pl-0123456789" open="1" />);
    expect(await screen.findByText("The items have no category, so the list can have no volume discount.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add a rule" })).toBeNull();
  });
});
