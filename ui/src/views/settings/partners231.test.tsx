// 231 (plan stage B, B1; DECISIONS 231): the partner register in Settings. The list finds partners by name, tax number,
// email or role; a partner opens with its versions; a new one is recorded once it has a name and a role; a change is
// saved as a new version; a conflict with another partner leads to that one; the domains' proposals show on request and
// a person records one. 263 (E1): the partners are the one list; a partner, a new one and the proposals are pages of
// their own. Synthetic data, a mocked service.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setActor, type Partner, type PartnerRoles, type PartnerRow } from "../../api";
import { setLanguage } from "../../i18n";
import { Settings } from "../Settings";
import { listPage, linkCol } from "./listPage.testutil";
import { PartnersPanel } from "./PartnersPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); window.location.hash = ""; localStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const ROLES: PartnerRoles = {
  customer: { label: "Customer", what: "Asks for a quote" }, supplier: { label: "Supplier", what: "Sells to us" },
  insured: { label: "Insured", what: "Insured" }, broker: { label: "Broker", what: "Brings a case" },
};
const ROW: PartnerRow = { partner_id: "partner-000000000001", name: "Invented Buyer Ltd", tax_number: "12345678-2-42",
  email: "buyer@example.com", phone: null, address: null, note: null, roles: ["customer"], version: 2, retired: false,
  changed_at: "2026-10-24T10:00:00+00:00" };
const PARTNER: Partner = { ...ROW, versions: [
  { ...ROW, version: 2, state: "active", made_by: "bela", made_at: "2026-10-24T10:00:00+00:00", activated_at: null, retired_by: null, retired_at: null },
  { ...ROW, version: 1, state: "superseded", made_by: "anna", made_at: "2026-10-20T10:00:00+00:00", activated_at: null, retired_by: null, retired_at: null }] };

describe("the partner register (231 B1; 263 E1: the one list, a partner's own page)", () => {
  it("lists the partners and opens one with its versions; a change is saved as a new version", async () => {
    vi.spyOn(api, "datasetQuery").mockResolvedValue(listPage("settings_partners",
      [linkCol("name", "Name", "partners"), { key: "tax_number", label: "Tax number", kind: "id", hidden: false, labels: null }],
      [{ _key: ROW.partner_id, name: ROW.name, tax_number: ROW.tax_number }]));
    const { unmount } = render(<PartnersPanel />);
    const table = await screen.findByRole("table", { name: "Partners" });
    expect(within(table).getByText("12345678-2-42")).toBeTruthy();
    expect(within(table).getByRole("link", { name: "Invented Buyer Ltd" }).getAttribute("href")).toBe("#/settings/partners/partner-000000000001");
    unmount();
    vi.spyOn(api, "partners").mockResolvedValue({ partners: [ROW], roles: ROLES, own: [] });
    vi.spyOn(api, "partner").mockResolvedValue(PARTNER);
    const update = vi.spyOn(api, "updatePartner").mockResolvedValue({ ...PARTNER, version: 3 });
    render(<PartnersPanel item="partner-000000000001" />);
    const card = await screen.findByRole("region", { name: "Invented Buyer Ltd" });
    const versions = within(card).getByRole("table", { name: "Versions" });
    expect(within(versions).getAllByRole("row")).toHaveLength(3);
    await act(async () => {});  // the card's loads and effects settle first (a late one reset the change under load)
    const save = () => within(card).getByRole("button", { name: "Save as a new version" }) as HTMLButtonElement;
    expect(save().disabled).toBe(true);  // nothing changed yet
    fireEvent.click(within(card).getByRole("checkbox", { name: "Supplier" }));
    await waitFor(() => expect(save().disabled).toBe(false));
    expect(save().className).toBe("primary");
    fireEvent.click(save());
    await waitFor(() => expect(update).toHaveBeenCalledWith("partner-000000000001",
      expect.objectContaining({ roles: ["customer", "supplier"] }), 2));
  });

  it("records a new partner and leads to the other one on a conflict", async () => {
    vi.spyOn(api, "partners").mockResolvedValue({ partners: [ROW], roles: ROLES, own: [] });
    const create = vi.spyOn(api, "createPartner").mockRejectedValue(
      new ApiError(409, "partner_conflict", "another partner has the same tax number or name", [], { other: "partner-000000000001" }));
    render(<PartnersPanel item="new" />);
    const card = await screen.findByRole("region", { name: "New partner" });
    await act(async () => {});
    const record = within(card).getByRole("button", { name: "Record the partner" }) as HTMLButtonElement;
    expect(record.disabled).toBe(true);
    fireEvent.change(within(card).getByRole("textbox", { name: "Name" }), { target: { value: "Invented Buyer" } });
    fireEvent.click(within(card).getByRole("checkbox", { name: "Customer" }));
    fireEvent.click(record);
    await waitFor(() => expect(create).toHaveBeenCalled());
    fireEvent.click(await within(card).findByRole("button", { name: "Open it" }));
    expect(window.location.hash).toBe("#/settings/partners/partner-000000000001");
  });

  it("shows the proposals on request and a person records one", async () => {
    vi.spyOn(api, "partners").mockResolvedValue({ partners: [], roles: ROLES, own: [] });
    const proposals = vi.spyOn(api, "partnerSuggestions").mockResolvedValue({ suggestions: [
      { name: "Invented Supplier Kft.", tax_number: "12121216-2-42", roles: ["supplier"], seen: 3, sources: ["invoices"], last: "2026-09-30" }] });
    const { rerender } = render(<Settings section="partners" item="proposals" />);
    const show = await screen.findByRole("button", { name: "Show the proposals" });  // the page's main action
    expect(proposals).not.toHaveBeenCalled();  // reading them goes through every invoice: only on request
    fireEvent.click(show);
    const table = await screen.findByRole("table", { name: "Proposals" });
    fireEvent.click(within(table).getByRole("button", { name: "Accept" }));
    expect(window.location.hash).toBe("#/settings/partners/new");
    rerender(<Settings section="partners" item="new" />);  // the address's new page, the proposal taken
    const card = await screen.findByRole("region", { name: "New partner" });
    expect((within(card).getByRole("textbox", { name: "Name" }) as HTMLInputElement).value).toBe("Invented Supplier Kft.");
    expect((within(card).getByRole("checkbox", { name: "Supplier" }) as HTMLInputElement).checked).toBe(true);
  });
});

describe("a case's partners (231 B1)", () => {
  const page = (link: Record<string, unknown>) => ({
    case: { id: "wp-000000000231", pack: "it_quote", version: "1.2.0", title: "IT quote", name: "Quote", status: "open" },
    steps: {}, next: null,
    tabs: [{ id: "request", label: "Request", elements: [{ type: "partner_link", step: null, data: { links: [
      { role: "customer", role_label: "Customer", partner: null, proposal: null, match: null, ...link }] } }] }],
  });

  it("records the record's customer as a partner and links it", async () => {
    const { CasePage } = await import("../CasePage");
    vi.spyOn(api, "casePage").mockResolvedValue(page({ proposal: { name: "Invented Buyer Ltd", tax_number: "12345678-2-42" } }) as never);
    const create = vi.spyOn(api, "createPartner").mockResolvedValue({ ...PARTNER, partner_id: "partner-000000000009" });
    const link = vi.spyOn(api, "linkCasePartner").mockResolvedValue(page({}) as never);
    render(<CasePage caseId="wp-000000000231" tab="request" />);
    const card = await screen.findByRole("region", { name: "Partners" });
    expect(within(card).getByText("Not in the partner register yet.")).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "Record as a partner" }));
    await waitFor(() => expect(link).toHaveBeenCalledWith("wp-000000000231", "customer", "partner-000000000009"));
    expect(create).toHaveBeenCalledWith(expect.objectContaining({ name: "Invented Buyer Ltd", tax_number: "12345678-2-42", roles: ["customer"] }));
  });

  it("offers the partner the record seems to be", async () => {
    const { CasePage } = await import("../CasePage");
    vi.spyOn(api, "casePage").mockResolvedValue(page({ proposal: { name: "Invented Buyer" },
      match: { partner_id: "partner-000000000001", name: "Invented Buyer Ltd", tax_number: null, email: null, roles: ["customer"], retired: false, version: 1 } }) as never);
    const link = vi.spyOn(api, "linkCasePartner").mockResolvedValue(page({}) as never);
    render(<CasePage caseId="wp-000000000231" tab="request" />);
    const card = await screen.findByRole("region", { name: "Partners" });
    expect(within(card).getByText(/It seems to be Invented Buyer Ltd/)).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "Link it" }));
    await waitFor(() => expect(link).toHaveBeenCalledWith("wp-000000000231", "customer", "partner-000000000001"));
  });
});
