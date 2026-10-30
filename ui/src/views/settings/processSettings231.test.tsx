// 231 (plan stage B, B4; DECISIONS 231): a process's own settings in Settings. The page lists what the process uses and
// the rule values its steps let it set, each with the value in use and the file's; a value opens with its versions; a
// new value is saved as a draft (a rule's whole number within its bounds), tried on the process's earlier decisions
// and made active; an active own value can be set aside. Synthetic data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type ProcessSettings, type RulePreview } from "../../api";
import { setLanguage } from "../../i18n";
import { parseRoute, routeHash } from "../../route";
import { linkCol, listPage } from "./listPage.testutil";
import { ProcessSettingsPanel } from "./ProcessSettingsPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const AT = "2026-10-25T09:00:00+00:00";
const PAGE: ProcessSettings = {
  pack: { id: "invented_quote", title: "Invented quote", version: "1.0.0" },
  resources: [
    { key: "send_mode", label: "Send mode", options: [{ value: "output_folder", label: "Into the output folder" },
      { value: "outlook_draft", label: "As a draft in the person's Outlook" }],
      file_value: "output_folder", value: "outlook_draft", own: true, versions: [
        { version: 1, state: "active", value: "outlook_draft", note: "the office sends from Outlook", made_by: "anna", made_at: AT, activated_by: "anna", activated_at: AT }] },
  ],
  rules: [
    { key: "quotes.draft.max_lines", file: "quotes", path: "draft.max_lines", what: "A quote holds at most this many lines",
      kind: "int", least: 1, most: 1000, options: [], steps: ["compose"], file_value: 300, value: 300, own: false, versions: [] },
  ],
  partners: [{ role: "customer", label: "Customer", step: "request", step_title: "Request" }],
  policy: { activation: "editor", owners: [] },
  description: { summary: "An invented quote from a request.", outputs: [], goldens: ["invented:lines"], examples: false,
    intake: [{ on: "manual", starts: "manual", intent: null }],
    steps: [{ id: "request", title: "Request", uses: "record_assembly@1", summary: "Reads the request.", start: "auto", after: [], optional: false },
      { id: "compose", title: "Quote", uses: "line_draft@1", summary: "Drafts the lines.", start: "person", after: ["Request"], optional: false }] },
};
const DRAFTED: ProcessSettings = { ...PAGE, rules: [{ ...PAGE.rules[0], versions: [
  { version: 1, state: "draft", value: 40, note: null, made_by: "Synthetic reviewer", made_at: AT, activated_by: null, activated_at: null }] }] };
const PREVIEW: RulePreview = { key: "quotes.draft.max_lines", value: 40, file_value: 300, decisions: 12, changed: 2, failed: 0,
  first_error: null, examples: [{ point: "invented.lines", subject: "case:c1", case_id: "wp-000000000001", case: "Quote: Invented Buyer", at: AT, before: true, after: false }] };

describe("a process's own settings (231 B4)", () => {
  it("shows the value in use beside the file's, and where it comes from", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [PAGE.pack] });
    vi.spyOn(api, "processSettings").mockResolvedValue(PAGE);
    const { rerender } = render(<ProcessSettingsPanel pack="invented_quote" tab="uses" />);  // 231 (U3a): its tabs
    const resources = await screen.findByRole("table", { name: "Resources" });
    const row = within(resources).getByRole("button", { name: "Send mode" }).closest("tr")!;
    expect(within(row).getByText("As a draft in the person's Outlook")).toBeTruthy();
    expect(within(row).getByText("Into the output folder")).toBeTruthy();
    expect(within(row).getByText("Own value")).toBeTruthy();
    expect(screen.getByText("The person who saves a value may make it active.", { exact: false })).toBeTruthy();
    rerender(<ProcessSettingsPanel pack="invented_quote" tab="values" />);
    const rules = await screen.findByRole("table", { name: "Rule values" });
    expect(within(rules).getByText("From the file")).toBeTruthy();
    rerender(<ProcessSettingsPanel pack="invented_quote" tab="partners" />);
    expect(await screen.findByText("Customer", { exact: false })).toBeTruthy();
  });

  it("says when the installation's default is in use, the value a new case keeps (261 B2, F07)", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [PAGE.pack] });
    vi.spyOn(api, "processSettings").mockResolvedValue({ ...PAGE, rules: [{ ...PAGE.rules[0], value: 320, origin: "installation",
      installation_value: 320 }] });
    render(<ProcessSettingsPanel pack="invented_quote" tab="values" />);
    const rules = await screen.findByRole("table", { name: "Rule values" });
    const row = within(rules).getByRole("button", { name: "A quote holds at most this many lines" }).closest("tr")!;
    expect(within(row).getByText("320")).toBeTruthy();
    expect(within(row).getByText("300")).toBeTruthy();
    expect(within(row).getByText("The installation's default")).toBeTruthy();
    fireEvent.click(within(row).getByRole("button", { name: "A quote holds at most this many lines" }));
    const card = await screen.findByRole("region", { name: "A quote holds at most this many lines" });
    expect(within(card).getByText("The installation's default").nextElementSibling?.textContent).toBe("320");
  });

  it("saves a rule value as a draft within its bounds, tries it on earlier decisions and makes it active", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [PAGE.pack] });
    const load = vi.spyOn(api, "processSettings").mockResolvedValue(PAGE);
    const propose = vi.spyOn(api, "proposeSetting").mockResolvedValue(DRAFTED);
    const preview = vi.spyOn(api, "previewRule").mockResolvedValue(PREVIEW);
    const activate = vi.spyOn(api, "activateSetting").mockResolvedValue(DRAFTED);
    render(<ProcessSettingsPanel pack="invented_quote" tab="values" />);
    fireEvent.click(await screen.findByRole("button", { name: "A quote holds at most this many lines" }));
    const card = await screen.findByRole("region", { name: "A quote holds at most this many lines" });
    const save = within(card).getByRole("button", { name: "Save as a draft" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);  // nothing typed yet
    const input = within(card).getByRole("spinbutton", { name: "New value" });
    fireEvent.change(input, { target: { value: "5000" } });
    expect(save.disabled).toBe(true);
    expect(within(card).getByText("A whole number from 1 to 1000.")).toBeTruthy();
    fireEvent.change(input, { target: { value: "40" } });
    fireEvent.click(within(card).getByRole("button", { name: "Try it on earlier decisions" }));
    await waitFor(() => expect(preview).toHaveBeenCalledWith("invented_quote", "quotes.draft.max_lines", 40));
    expect(await within(card).findByText(/2 of the process's 12 earlier decisions would come out differently/)).toBeTruthy();
    fireEvent.change(within(card).getByRole("textbox", { name: "Note" }), { target: { value: "short quotes" } });
    fireEvent.click(save);
    await waitFor(() => expect(propose).toHaveBeenCalledWith("invented_quote", "rules", "quotes.draft.max_lines", 40, "short quotes"));
    load.mockResolvedValue(DRAFTED);
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    const versions = await within(await screen.findByRole("region", { name: "A quote holds at most this many lines" })).findByRole("table", { name: "Versions" });
    fireEvent.click(within(versions).getByRole("button", { name: "Make active" }));
    await waitFor(() => expect(activate).toHaveBeenCalledWith("invented_quote", "rules", "quotes.draft.max_lines", 1));
  });

  it("chooses a resource's value from its options and sets an own value aside", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [PAGE.pack] });
    vi.spyOn(api, "processSettings").mockResolvedValue(PAGE);
    const propose = vi.spyOn(api, "proposeSetting").mockResolvedValue(PAGE);
    const retire = vi.spyOn(api, "retireSetting").mockResolvedValue(PAGE);
    render(<ProcessSettingsPanel pack="invented_quote" tab="uses" />);
    fireEvent.click(await screen.findByRole("button", { name: "Send mode" }));
    const card = await screen.findByRole("region", { name: "Send mode" });
    fireEvent.change(within(card).getByRole("combobox", { name: "New value" }), { target: { value: "output_folder" } });
    fireEvent.click(within(card).getByRole("button", { name: "Save as a draft" }));
    await waitFor(() => expect(propose).toHaveBeenCalledWith("invented_quote", "settings", "send_mode", "output_folder", null));
    expect(within(card).queryByRole("button", { name: "Try it on earlier decisions" })).toBeNull();  // a resource has no preview
    const versions = within(card).getByRole("table", { name: "Versions" });
    const aside = within(versions).getByRole("button", { name: "Use the file's value" });
    fireEvent.click(aside);
    fireEvent.click(within(versions).getByRole("button", { name: /Sure/ }));
    await waitFor(() => expect(retire).toHaveBeenCalledWith("invented_quote", "settings", "send_mode"));
  });

  it("lists the processes, each at its own address, and describes one on its first tab (231 U3a)", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [{ ...PAGE.pack, summary: "An invented quote from a request." }] });
    vi.spyOn(api, "processSettings").mockResolvedValue(PAGE);
    // 263 (E1): the processes are the one list (a dataset); a row opens the process's page
    vi.spyOn(api, "datasetQuery").mockResolvedValue(listPage("settings_processes", [linkCol("title", "Process", "processes")],
      [{ _key: "invented_quote", title: "Invented quote" }]));
    const { rerender } = render(<ProcessSettingsPanel />);
    const list = await screen.findByRole("table", { name: "Processes" });
    expect(within(list).getByRole("link", { name: "Invented quote" }).getAttribute("href")).toBe("#/settings/processes/invented_quote");
    rerender(<ProcessSettingsPanel pack="invented_quote" />);
    const tabs = await screen.findByRole("tablist", { name: "The process's settings" });
    expect(within(tabs).getByRole("tab", { name: "Description" }).getAttribute("aria-selected")).toBe("true");
    expect(within(tabs).getByRole("tab", { name: "What it uses" }).getAttribute("href")).toBe("#/settings/processes/invented_quote/uses");
    const steps = screen.getByRole("table", { name: "Its steps" });
    expect(within(steps).getByText("Drafts the lines.")).toBeTruthy();
    expect(within(steps).getByText(/A person starts it/).textContent).toContain("after Request");
    expect(screen.getByText("A person starts it from New case.")).toBeTruthy();
    expect(screen.getByText("invented:lines")).toBeTruthy();
    expect(parseRoute("#/settings/processes/it_quote/uses")).toEqual({ view: "settings", section: "processes", item: "it_quote", tab: "uses" });
    expect(routeHash({ view: "settings", section: "processes", item: "it_quote" })).toBe("#/settings/processes/it_quote");
  });

  it("names a value no active choice names by the library's name, a code only where none exists (263)", async () => {
    const named: ProcessSettings = { ...PAGE, resources: [{ ...PAGE.resources[0], key: "product", label: "Product", options: [],
      file_value: "invented_product", value: "invented_draft", own: false, versions: [],
      names: { invented_draft: "Invented product (a draft)" } }] };
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [PAGE.pack] });
    vi.spyOn(api, "processSettings").mockResolvedValue(named);
    render(<ProcessSettingsPanel pack="invented_quote" tab="uses" />);
    const row = (await screen.findByRole("button", { name: "Product" })).closest("tr")!;
    expect(within(row).getByText("Invented product (a draft)").className).not.toContain("mono");
    expect(within(row).getByText("invented_product").className).toContain("mono");  // no name: the code
  });

  it("says where the values come from when there is nothing to choose yet (231 U3b)", async () => {
    const empty: ProcessSettings = { ...PAGE, resources: [{ ...PAGE.resources[0], key: "product", label: "Product", options: [],
      file_value: "invented_product", value: "invented_product", own: false, versions: [] }] };
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [PAGE.pack] });
    vi.spyOn(api, "processSettings").mockResolvedValue(empty);
    render(<ProcessSettingsPanel pack="invented_quote" tab="uses" />);
    fireEvent.click(await screen.findByRole("button", { name: "Product" }));
    const card = await screen.findByRole("region", { name: "Product" });
    expect(within(card).getByRole("status").textContent).toContain("nothing to choose yet");
  });

  it("shows a tariff that follows from the product read only, and the old tariffs address opens the product's list (231 U3c)", async () => {
    const withTariff: ProcessSettings = { ...PAGE, resources: [
      { ...PAGE.resources[0], key: "product", label: "Product", options: [{ value: "invented_product", label: "Invented product" }],
        file_value: "invented_product", value: "invented_product", own: false, versions: [] },
      { ...PAGE.resources[0], key: "tariff", label: "Tariff", options: null, file_value: "invented_tariff", value: "invented_tariff",
        own: false, versions: [], derived_from: "product" }] };
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [PAGE.pack] });
    vi.spyOn(api, "processSettings").mockResolvedValue(withTariff);
    render(<ProcessSettingsPanel pack="invented_quote" tab="uses" />);
    const row = (await screen.findByRole("button", { name: "Tariff" })).closest("tr")!;
    expect(within(row).getByText("From the Product")).toBeTruthy();
    fireEvent.click(within(row).getByRole("button", { name: "Tariff" }));
    const card = await screen.findByRole("region", { name: "Tariff" });
    expect(within(card).getByRole("status").textContent).toBe("It follows from the Product: set the Product instead.");
    expect(within(card).queryByRole("button", { name: "Save as a draft" })).toBeNull();
    expect(parseRoute("#/settings/tariffs")).toEqual({ view: "settings", section: "products", item: "tariffs" });
  });
});
