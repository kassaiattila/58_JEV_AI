// 264 (plan G, G1; the owner's decision of 2026-10-31: partner proposals from the processed data, as the own parties have
// them): the proposals show at once; one is recorded at once, the selected ones or all of them too; one that is no
// partner is dismissed and restored from the dismissed ones; the partners' list says how many wait. Synthetic parties,
// a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DsColumn } from "../../api";
import { findConfirmAction } from "../../confirm.testutil";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { listPage } from "./listPage.testutil";
import { PartnersPanel } from "./PartnersPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic owner"); sessionStorage.clear(); window.location.hash = ""; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const NAME: DsColumn = { key: "name", label: "Name", kind: "text", hidden: false, labels: null };

function service() {
  vi.spyOn(api, "partners").mockResolvedValue({ partners: [], roles: {}, own: [] } as never);
  return vi.spyOn(api, "datasetQuery").mockImplementation(async (name) => (name === "settings_partner_proposals"
    ? listPage(name, [NAME], [
      { _key: "domestic:12345676", name: "Example Supplier Kft.", tax_number: "12345676-2-41", _roles: ["supplier"] },
      { _key: "name:buyer example", name: "Example Buyer Ltd", tax_number: null, _roles: ["customer"] }])
    : name === "settings_partner_dismissed"
      ? listPage(name, [NAME], [{ _key: "name:misread vendor ticket", name: "Misread Ticket Vendor" }])
      : listPage(name, [NAME], [])));
}

describe("the partner proposals", () => {
  it("records one at once, all of them at once, and dismisses and restores", async () => {
    service();
    const accept = vi.spyOn(api, "acceptPartnerSuggestions").mockResolvedValue({ created: ["partner-000000000001"], skipped: 0 });
    const dismiss = vi.spyOn(api, "dismissPartnerSuggestions").mockResolvedValue({ dismissed: [] });
    const restore = vi.spyOn(api, "restorePartnerSuggestions").mockResolvedValue({ restored: [] });
    render(<PartnersPanel item="proposals" />);
    const table = await screen.findByRole("table", { name: "Proposals" });
    const row = (await within(table).findByText("Example Supplier Kft.")).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Record" }));
    await waitFor(() => expect(accept).toHaveBeenLastCalledWith(["domestic:12345676"]));
    expect(await screen.findByText("1 recorded as partners.")).toBeTruthy();

    fireEvent.click(within((within(table).getByText("Example Buyer Ltd")).closest("tr") as HTMLElement).getByRole("button", { name: "Not a partner" }));
    await waitFor(() => expect(dismiss).toHaveBeenLastCalledWith(["name:buyer example"]));

    fireEvent.click(await screen.findByRole("button", { name: "Record all 2" }));
    fireEvent.click(await findConfirmAction());
    await waitFor(() => expect(accept).toHaveBeenLastCalledWith(null));

    const dismissed = screen.getByRole("table", { name: "Dismissed partner proposals" });
    fireEvent.click(await within(dismissed).findByRole("button", { name: "Restore" }));
    await waitFor(() => expect(restore).toHaveBeenLastCalledWith(["name:misread vendor ticket"]));
  });

  it("records or dismisses the selected ones", async () => {
    service();
    const accept = vi.spyOn(api, "acceptPartnerSuggestions").mockResolvedValue({ created: [], skipped: 2 });
    render(<PartnersPanel item="proposals" />);
    const table = await screen.findByRole("table", { name: "Proposals" });
    for (const name of ["Example Supplier Kft.", "Example Buyer Ltd"]) {
      await userEvent.click(within((await within(table).findByText(name)).closest("tr") as HTMLElement).getByRole("checkbox"));
    }
    fireEvent.click(screen.getByRole("button", { name: "Record the selected (2)" }));
    await waitFor(() => expect(accept).toHaveBeenLastCalledWith(["domestic:12345676", "name:buyer example"]));
    expect(await screen.findByText("0 recorded as partners; 2 skipped (a partner meanwhile, or seen in no role).")).toBeTruthy();
  });

  it("the partners' list says how many proposals wait", async () => {
    service();
    render(<PartnersPanel />);
    expect(await screen.findByRole("link", { name: "Suggestions from the data (2) →" })).toBeTruthy();
  });

  it("has its words in Hungarian", () => {
    const hu = hungarian as Record<string, string>;
    for (const key of ["Record all {{n}}", "Record the selected ({{n}})", "Not partners ({{n}})", "Record", "Edit first…", "Not a partner",
      "Dismissed proposals", "Nothing is dismissed.", "Restore", "{{n}} recorded as partners.", "Suggestions from the data ({{n}})",
      "{{n}} recorded as partners; {{m}} skipped (a partner meanwhile, or seen in no role).", "Dismissed: not proposed again until restored.",
      "Restored among the proposals."]) {
      expect(hu[key], key).toBeTruthy();
      expect(hu[key]).not.toBe(key);
    }
  });
});
