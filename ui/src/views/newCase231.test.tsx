// 231 (stage U, U0; the owner's decisions of 2026-10-27): a new case of any process from the case list. The page lists
// the processes a person may start by hand with what each is for; one that cannot start yet says what it needs and
// offers its example material, whose installation is then the page's main step; once installed, the process's own form
// starts the case, on a packet of the invented example documents too (the packet's files are written first). Synthetic
// data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type ProcessExamples, type ProcessRow } from "../api";
import { setLanguage } from "../i18n";
import { parseRoute, routeHash } from "../route";
import { CaseList } from "./CaseList";
import { NewCase } from "./NewCase";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.location.hash = ""; });

const CASE = "wp-000000000c01";
const OFFER: ProcessRow = { id: "offer_pack", title: "Insurance quote", version: "1.0.0", scope: ["source"], asks: ["source"],
  package_kinds: [], manual: true, summary: "A quote from documents.", examples: true,
  missing_at_start: [{ key: "product", label: "Product" }, { key: "tariff", label: "Tariff" }] };
const DOCS: ProcessRow = { id: "documents", title: "Documents", version: "1.0.0", scope: ["source"], asks: ["source"],
  package_kinds: [], manual: true, summary: "Documents read.", examples: false, missing_at_start: [] };
const HIDDEN: ProcessRow = { ...DOCS, id: "auto_only", title: "Only by itself", manual: false };
const EXAMPLES = (state: "installed" | "missing"): ProcessExamples => ({
  sets: [{ kind: "product_set", name: "invented", title: "Invented insurer: Business property", state, example: state === "installed" }],
  packets: [{ id: "reference", title: "A complete request", documents: 3 }],
});

describe("the case list starts a new case (231 U0)", () => {
  it("has a New case link and its address", async () => {
    vi.spyOn(api, "datasetQuery").mockResolvedValue({ rows: [], total: 0 } as never);
    render(<CaseList />);
    expect(screen.getByRole("link", { name: "New case" }).getAttribute("href")).toBe("#/cases/new");
    expect(parseRoute("#/cases/new")).toEqual({ view: "case-list", create: true });
    expect(parseRoute("#/cases/new/offer_pack")).toEqual({ view: "case-list", create: true, pack: "offer_pack" });
    expect(routeHash({ view: "case-list", create: true, pack: "offer_pack" })).toBe("#/cases/new/offer_pack");
    expect(parseRoute("#/cases/wp-000000000c01")).toEqual({ view: "cases", caseId: "wp-000000000c01", tab: undefined });
  });
});

describe("the new case page (231 U0)", () => {
  it("lists the processes a person starts, and says what one cannot start without", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [OFFER, DOCS, HIDDEN] });
    render(<NewCase />);
    expect(await screen.findByRole("radio", { name: "Insurance quote" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Documents" })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: "Only by itself" })).toBeNull();
    expect(screen.getByText("A quote from documents.")).toBeTruthy();
    expect(screen.getByText("Before a case can start: Product, Tariff needs an active version.")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Documents" }));
    expect(window.location.hash).toBe("#/cases/new/documents");
  });

  it("installs the example material as the main step, then starts a case on an example packet", async () => {
    const processes = vi.spyOn(api, "processes").mockResolvedValue({ processes: [OFFER, DOCS] });
    vi.spyOn(api, "processExamples").mockResolvedValueOnce(EXAMPLES("missing")).mockResolvedValue(EXAMPLES("installed"));
    const install = vi.spyOn(api, "installExamples").mockResolvedValue(EXAMPLES("installed"));
    vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
    vi.spyOn(api, "parties").mockResolvedValue({ parties: [] } as never);
    const files = vi.spyOn(api, "examplePacketFiles").mockResolvedValue({ files: ["C:\\store\\examples\\a.pdf", "C:\\store\\examples\\b.pdf"] });
    const start = vi.spyOn(api, "startCase").mockResolvedValue({ case_id: CASE });
    render(<NewCase pack="offer_pack" />);
    const installButton = await screen.findByRole("button", { name: "Install the example material" });
    expect(installButton.className).toBe("primary");  // the case cannot start without it
    expect(screen.getByText("Not installed")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Create" })).toBeNull();

    processes.mockResolvedValue({ processes: [{ ...OFFER, missing_at_start: [] }, DOCS] });
    fireEvent.click(installButton);
    await waitFor(() => expect(install).toHaveBeenCalledWith("offer_pack"));
    expect(await screen.findByRole("button", { name: "Remove the example material" })).toBeTruthy();
    fireEvent.click(await screen.findByRole("radio", { name: "Example documents" }));
    fireEvent.change(screen.getByLabelText("The packet of invented documents"), { target: { value: "reference" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(start).toHaveBeenCalled());
    expect(files).toHaveBeenCalledWith("offer_pack", "reference");
    expect(start).toHaveBeenCalledWith({ pack: "offer_pack", name: "Insurance quote · Example: A complete request",
      source: { kind: "files", files: ["C:\\store\\examples\\a.pdf", "C:\\store\\examples\\b.pdf"] } });
    await waitFor(() => expect(window.location.hash).toBe(`#/cases/${CASE}`));
  });
});
