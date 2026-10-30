// 179 (plan 170 L4, DECISIONS 178/179): own output templates in the interface - Settings › Output templates (upload with
// the check's problems by cell, the versions with their state, activation and retirement, the markers to copy) and the
// template chooser next to a package's downloads (the owner's decision of 2026-10-19), which shows only when an own
// template can be chosen. The local service is replaced by spies; synthetic names and paths only.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api, ApiError, setActor, type OutputMarkerGroup, type OutputTemplate, type OutputTemplateCheck, type OutputTemplateVersion,
  type OutputName, type OutputTemplatesListing, type PackageOutputChoices,
} from "../../api";
import { TemplateChoice } from "../../components/TemplateChoice";
import { setLanguage } from "../../i18n";
import { UtilityPanel } from "../../domains/finance/UtilityReport";
import { linkCol, listPage } from "./listPage.testutil";
import { issueText, OutputTemplatesPanel } from "./OutputTemplatesPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const CHECK: OutputTemplateCheck = { output: "package_result", ok: true, problems: [], warnings: [], values: ["package"], tables: {} };

function version(over: Partial<OutputTemplateVersion> = {}): OutputTemplateVersion {
  return {
    template: "tpl-0123456789", output: "package_result", name: "Board report", version: 1, state: "draft", file_name: "board.xlsx",
    sha256: "0".repeat(64), uploaded_by: "Synthetic reviewer", uploaded_at: "2026-10-19T10:00:00+00:00", activated_by: null,
    activated_at: null, retired_by: null, retired_at: null, check: CHECK, size: 12000, ...over,
  };
}

const GROUPS: OutputMarkerGroup[] = [
  { table: null, part: null, label: null, count: null, months: null,
    rows: [{ marker: "{{package}}", label: "Package", kind: "text", sum: null }] },
  { table: "documents", part: "invoice_hu", label: "Synthetic invoice", count: "{{invoice_hu:count}}", months: null,
    rows: [{ marker: "{{invoice_hu.gross_total}}", label: "Gross total", kind: "money", sum: "{{invoice_hu.gross_total:sum}}" }] },
  { table: "utility_cost", part: null, label: null, count: "{{utility_cost:count}}",
    months: { row: "{{utility_cost.months}}", names: "{{utility_cost.months:names}}" },
    rows: [{ marker: "{{utility_cost.address}}", label: "Consumption place", kind: "text", sum: null }] },
];

function listing(templates: OutputTemplate[]): OutputTemplatesListing {
  const out = (o: OutputName) => ({ output: o, what: "", format: o === "quote" ? "docx" as const : "xlsx" as const,
    markers: o === "package_result" ? GROUPS : [] });
  return { templates, outputs: { package_result: out("package_result"), utility_cost: out("utility_cost"),
    reconcile_statement: out("reconcile_statement"), quote: out("quote") } };
}

const board = (versions: OutputTemplateVersion[]): OutputTemplate => ({
  template: "tpl-0123456789", output: "package_result", name: "Board report",
  active: versions.find((v) => v.state === "active")?.version ?? null, retired: versions.some((v) => v.state === "retired"), versions,
});

describe("Settings › Output templates (179)", () => {
  it("shows each output's versions with their state, and says the built-in template makes an output without one", async () => {
    vi.spyOn(api, "outputTemplates").mockResolvedValue(listing([board([version({ version: 2, state: "draft" }), version({ state: "active" })])]));
    const { unmount } = render(<OutputTemplatesPanel item="tpl-0123456789" />);  // 263: a template's own page
    await screen.findByText("Board report");
    const rows = within(document.querySelector(".template-table") as HTMLElement).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByText(/^(Draft|Active)$/).textContent)).toEqual(["Draft", "Active"]);
    expect(within(rows[0]).getByText("Draft").className).toContain("s-trial");
    expect(within(rows[1]).getByText("Active").className).toContain("s-done");
    // the active version is retired, an older one or a draft made active; each version has its preview and its file
    expect(within(rows[0]).getByRole("button", { name: "Make active" })).toBeTruthy();
    expect(within(rows[1]).getByRole("button", { name: "Retire" })).toBeTruthy();
    expect(within(rows[0]).getByRole("link", { name: "Preview (made-up data)" }).getAttribute("href"))
      .toBe("/api/output-templates/tpl-0123456789/versions/2/preview.xlsx");
    unmount();
    // 263: the templates are the one list; without one, every download is made by the built-in template
    vi.spyOn(api, "datasetQuery").mockResolvedValue(listPage("settings_output_templates", [linkCol("name", "Name", "outputs")], []));
    render(<OutputTemplatesPanel />);
    expect(await screen.findByText("No own template: the built-in template makes every download.")).toBeTruthy();
  });

  it("names every problem of a refused upload with its cell, and stores nothing", async () => {
    vi.spyOn(api, "outputTemplates").mockResolvedValue(listing([]));
    const check: OutputTemplateCheck = { ...CHECK, ok: false, problems: [
      { code: "formula", where: "Sheet1!B4", detail: "" },
      { code: "unknown_marker", where: "Sheet1!A2", detail: "{{invoices.amount}}: no table invoices" },
    ], warnings: [{ code: "conditional_formatting", where: "Sheet1", detail: "" }] };
    const upload = vi.spyOn(api, "uploadOutputTemplate").mockRejectedValue(new ApiError(422, "template_refused", "refused", [], {}, check));
    render(<OutputTemplatesPanel item="new" />);  // 263: the upload's own page
    const button = await screen.findByRole("button", { name: "Upload and check" });
    expect(button).toHaveProperty("disabled", true); // a form's main step is solid and disabled until it is complete
    expect(button.className).toContain("primary");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Board report" } });
    fireEvent.change(screen.getByLabelText("The workbook's full path (.xlsx)"), { target: { value: "D:\\Synthetic\\board.xlsx" } });
    fireEvent.click(button);
    const alert = await screen.findByRole("alert");
    expect(upload).toHaveBeenCalledWith({ output: "package_result", name: "Board report", path: "D:\\Synthetic\\board.xlsx" });
    expect(alert.textContent).toContain("the check found 2 problem(s)");
    expect(within(alert).getByText("Sheet1!B4")).toBeTruthy();
    expect(within(alert).getByText(issueText("formula"))).toBeTruthy();
    // an unknown marker is named in the code face, the check's reason in words
    expect(within(alert).getByText("{{invoices.amount}}").className).toContain("mono");
    expect(within(alert).getByText("the output has no table invoices")).toBeTruthy();
    expect(within(alert).getByText(issueText("conditional_formatting")).closest("li")?.className).toBe("warning");
  });

  it("uploads a new version of a template with its output, and says it is a draft", async () => {
    const load = vi.spyOn(api, "outputTemplates").mockResolvedValue(listing([board([version({ state: "active" })])]));
    const upload = vi.spyOn(api, "uploadOutputTemplate").mockResolvedValue(version({ version: 2 }));
    window.location.hash = "";
    render(<OutputTemplatesPanel item="tpl-0123456789" tab="upload" />);  // 263: a new version's own page
    expect(await screen.findByRole("heading", { name: "New version of Board report" })).toBeTruthy();
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("Board report");
    fireEvent.change(screen.getByLabelText("The workbook's full path (.xlsx)"), { target: { value: "D:\\Synthetic\\board2.xlsx" } });
    fireEvent.click(screen.getByRole("button", { name: "Upload and check" }));
    await waitFor(() => expect(window.location.hash).toBe("#/settings/outputs/tpl-0123456789"));  // back to the template's page
    expect(upload).toHaveBeenCalledWith({ output: "package_result", name: "Board report", path: "D:\\Synthetic\\board2.xlsx", template: "tpl-0123456789" });
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("makes a version active and retires the active one (with a confirmation)", async () => {
    vi.spyOn(api, "outputTemplates").mockResolvedValue(listing([board([version({ version: 2 }), version({ state: "active" })])]));
    const activate = vi.spyOn(api, "activateOutputTemplate").mockResolvedValue(version({ version: 2, state: "active" }));
    const retire = vi.spyOn(api, "retireOutputTemplate").mockResolvedValue(version({ state: "retired" }));
    render(<OutputTemplatesPanel item="tpl-0123456789" />);
    fireEvent.click(await screen.findByRole("button", { name: "Make active" }));
    expect(await screen.findByText(/Active: Board report, version 2/)).toBeTruthy();
    expect(activate).toHaveBeenCalledWith("tpl-0123456789", 2);
    const r = screen.getByRole("button", { name: "Retire" });
    fireEvent.click(r);
    expect(retire).not.toHaveBeenCalled();
    fireEvent.click(r);
    await waitFor(() => expect(retire).toHaveBeenCalledWith("tpl-0123456789"));
  });

  it("lists the markers to copy, with a column's total, a table's row count and the months, and searches them", async () => {
    vi.spyOn(api, "outputTemplates").mockResolvedValue(listing([]));
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText: write }, configurable: true });
    render(<OutputTemplatesPanel item="markers" />);  // 263: the markers' own page
    const card = await screen.findByRole("region", { name: "Markers" });
    const table = card.querySelector(".marker-table") as HTMLElement; // the help above it shows examples too
    for (const m of ["{{package}}", "{{invoice_hu.gross_total}}", "{{invoice_hu.gross_total:sum}}", "{{invoice_hu:count}}",
      "{{utility_cost.months}}", "{{utility_cost.months:names}}"]) {
      expect(within(table).getByText(m)).toBeTruthy();
    }
    expect(within(table).getByText("Documents: Synthetic invoice")).toBeTruthy();
    fireEvent.click(within(table).getByRole("button", { name: "Copy {{invoice_hu.gross_total}}" }));
    await waitFor(() => expect(write).toHaveBeenCalledWith("{{invoice_hu.gross_total}}"));
    fireEvent.change(within(card).getByLabelText("Search"), { target: { value: "gross" } });
    expect(within(table).queryByText("{{package}}")).toBeNull();
    expect(within(table).getByText("{{invoice_hu.gross_total}}")).toBeTruthy();
  });
});

const choices = (over: Partial<PackageOutputChoices["outputs"]["package_result"]> = {}): PackageOutputChoices => ({
  workpackage_id: "wp-000000000001",
  outputs: { package_result: { chosen: null, templates: [{ template: "tpl-0123456789", name: "Board report", version: 2 }], decision_state: 3, ...over },
    utility_cost: { chosen: null, templates: [] } },
});

describe("the template chooser next to a download (179)", () => {
  it("shows nothing when no own template can be chosen", async () => {
    const load = vi.spyOn(api, "packageOutputTemplates").mockResolvedValue(choices());
    const { container } = render(<TemplateChoice wpId="wp-000000000001" output="utility_cost" />);
    await waitFor(() => expect(load).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });

  it("chooses an own template, and the built-in one again", async () => {
    vi.spyOn(api, "packageOutputTemplates").mockResolvedValue(choices());
    const choose = vi.spyOn(api, "choosePackageOutputTemplate").mockResolvedValue(choices());
    render(<TemplateChoice wpId="wp-000000000001" output="package_result" />);
    const trigger = await screen.findByRole("button", { name: /Template of the download/ });
    expect(trigger.textContent).toContain("Built-in");
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: /Board report/ }));
    await waitFor(() => expect(choose).toHaveBeenCalledWith("wp-000000000001", "package_result", "tpl-0123456789", 3));  // 187: with the state it read
    fireEvent.click(screen.getByRole("button", { name: /Template of the download/ }));
    fireEvent.click(screen.getByRole("option", { name: /Built-in/ }));
    await waitFor(() => expect(choose).toHaveBeenLastCalledWith("wp-000000000001", "package_result", null, 3));
  });

  it("says when the chosen template was retired and the built-in one is used", async () => {
    vi.spyOn(api, "packageOutputTemplates").mockResolvedValue(choices({
      chosen: { template: "tpl-0123456789", chosen_by: "Synthetic reviewer", chosen_at: "2026-10-19T10:00:00+00:00", active: false, name: null, version: null },
      templates: [] }));
    render(<TemplateChoice wpId="wp-000000000001" output="package_result" />);
    expect((await screen.findByText("the chosen template was retired; the built-in one is used")).className).toContain("s-warn");
    expect(screen.getByRole("button", { name: /Template of the download/ }).textContent).toContain("Built-in");
  });

  it("gives the package's utility cost its own download, beside its chooser", async () => {
    vi.spyOn(api, "packageUtilityCost").mockResolvedValue({ months: [], series: [], grand_total: "0", duplicates: [], unplaced: [] } as never);
    vi.spyOn(api, "packageOutputTemplates").mockResolvedValue(choices({}));
    render(<UtilityPanel wpId="wp-000000000001" />);
    const link = await screen.findByRole("link", { name: "Utility cost (Excel)" });
    expect(link.getAttribute("href")).toBe("/api/workpackages/wp-000000000001/result/utility-cost.xlsx");
  });

  it("gives a run's utility cost no download of its own (the run's full Excel package has it)", async () => {
    const run = vi.spyOn(api, "utilityCost").mockResolvedValue({ months: [], series: [], grand_total: "0", duplicates: [], unplaced: [] } as never);
    const load = vi.spyOn(api, "packageOutputTemplates");
    render(<UtilityPanel wpId="wp-000000000001" runId="run-000000000001" />);
    await waitFor(() => expect(run).toHaveBeenCalled());
    expect(screen.queryByRole("link", { name: "Utility cost (Excel)" })).toBeNull();
    expect(load).not.toHaveBeenCalled();
  });
});

describe("Settings › Output templates: a Word template (196)", () => {
  it("previews a quote's template as a Word document and names a Word template's problems", async () => {
    const offer = version({ template: "tpl-00000000aa", output: "quote", name: "Our offer", state: "active", file_name: "offer.docx",
      check: { ...CHECK, output: "quote" } });
    vi.spyOn(api, "outputTemplates").mockResolvedValue(listing([{ template: "tpl-00000000aa", output: "quote", name: "Our offer",
      active: 1, retired: false, versions: [offer] }]));
    render(<OutputTemplatesPanel item="tpl-00000000aa" />);
    await screen.findByText("Our offer");
    expect(screen.getByRole("link", { name: "Preview (made-up data)" }).getAttribute("href"))
      .toBe("/api/output-templates/tpl-00000000aa/versions/1/preview.docx");
    expect(issueText("not_docx")).toBe("The file is not a Word document (.docx).");
    expect(issueText("field")).toContain("A template holds no calculation");
    expect(issueText("attached_template")).toContain("removed");
  });
});
