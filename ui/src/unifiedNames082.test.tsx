// 082 (the owner's request of 2026-10-01): the item lists can show the unified (content-based) file name instead of
// the original one — a switch above the lists, remembered per person, an „Egységes név” column that can be added, a
// warning mark on an uncertain name and a note while an item has no unified name yet. Artificial data, no service.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DsColumn, type DsPage, type DsRow, type RunView, type Workpackage } from "./api";
import { nameCell } from "./components/NameCell";
import { getNameMode, setNameMode } from "./names";
import { DocumentsPanel } from "./views/DocumentsPanel";
import { ReviewWorkspace } from "./views/ReviewWorkspace";

beforeEach(() => { localStorage.clear(); setActor("teszt.elek"); });
afterEach(() => vi.restoreAllMocks());

const NAME: DsColumn = { key: "name", label: "Tétel", kind: "text", hidden: false, labels: null, link: "review", names: "unified" };
const UNIFIED: DsColumn = { key: "unified_name", label: "Egységes név", kind: "text", hidden: true, labels: null, link: "review" };
const row = (over: Partial<DsRow>): DsRow => ({ _key: "a", _wp: "wp-1", item_id: "a", name: "2026-09-01_SZAMLA_Minta-Kft_A-1.pdf",
  original_name: "scan_0001.pdf", unified_name: "2026-09-01_SZAMLA_Minta-Kft_A-1.pdf", name_state: "ready", _name_check: null, ...over });
const page = (rows: DsRow[]): DsPage => ({ dataset: { name: "workpackage_items", label: "Csomag tételei", scope: ["workpackage_id"], optional_scope: ["names"], natural_sort: [] },
  columns: [NAME, UNIFIED], rows, total: rows.length, matched: rows.length, offset: 0, limit: 100, facets: {} });

describe("082 name choice", () => {
  it("the unified name is the default, and the choice is kept per person", () => {
    expect(getNameMode()).toBe("unified");
    setNameMode("original");
    expect(getNameMode()).toBe("original");
    setActor("minta.anna");
    expect(getNameMode()).toBe("unified");
    setActor("teszt.elek");
    expect(getNameMode()).toBe("original");
  });

  it("the package's document list asks the service for the chosen name, and the switch changes it", async () => {
    const query = vi.spyOn(api, "datasetQuery").mockResolvedValue(page([row({})]));
    render(<DocumentsPanel wp={{ id: "wp-1", revision: 3, source_kind: "folder", source_ref: "C:\\szamlak" } as Workpackage} onChanged={vi.fn()} />);
    await waitFor(() => expect(query).toHaveBeenCalledWith("workpackage_items", { workpackage_id: "wp-1", names: "unified" }, expect.anything()));
    await userEvent.setup().click(screen.getByRole("radio", { name: "Eredeti" }));
    await waitFor(() => expect(query).toHaveBeenLastCalledWith("workpackage_items", { workpackage_id: "wp-1", names: "original" }, expect.anything()));
    expect(getNameMode()).toBe("original");
  });
});

describe("082 name cell", () => {
  it("an uncertain unified name gets a warning mark with the reason, and the original name in the tooltip", () => {
    render(<>{nameCell(NAME, row({ name_state: "review", _name_check: "hiányzik: Számla sorszáma" }))}</>);
    expect(screen.getByLabelText("Ellenőrzendő név: hiányzik: Számla sorszáma")).toBeTruthy();
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("#/workpackages/wp-1/review/a");
    expect(link.getAttribute("title")).toBe("Eredeti név: scan_0001.pdf");
  });

  it("an item without a unified name keeps its original name with a note", () => {
    render(<>{nameCell(NAME, row({ name: "scan_0002.pdf", unified_name: null, name_state: "pending" }))}</>);
    const link = screen.getByRole("link", { name: /scan_0002\.pdf/ });
    expect(link.getAttribute("title")).toBe("Még nincs egységes név: a tétel még nem futott le.");
    render(<>{nameCell(UNIFIED, row({ unified_name: null, name_state: "pending" }))}</>);
    expect(screen.getByText("még nincs")).toBeTruthy();
  });

  it("with the original name chosen, the cell is left to the table", () => {
    expect(nameCell({ ...NAME, names: "original" }, row({ name: "scan_0001.pdf" }))).toBeUndefined();
    expect(nameCell({ ...NAME, key: "kind" }, row({}))).toBeUndefined();
  });
});

describe("082 review queue", () => {
  it("the queue shows the unified names with the warning mark and finds an item by either name", async () => {
    const runs: DsPage = { ...page([]), rows: [{ _key: "run-1", run_id: "run-1" }], total: 1, matched: 1 };
    vi.spyOn(api, "datasetQuery").mockResolvedValue(runs);
    const view = {
      run: { run_id: "run-1", approval: null, items: [{ item_id: "a", status: "done", final_status: "done" }, { item_id: "b", status: "done", final_status: "needs_review" }],
        input: { items: [{ item_id: "a", source_path: "C:\\szamlak\\scan_0001.pdf" }, { item_id: "b", source_path: "C:\\szamlak\\scan_0002.pdf" }] } },
      titles: {}, open_reasons: { a: [], b: [] }, earlier_open_reasons: {},
      names: { a: { unified: "2026-09-01_SZAMLA_Minta-Kft_A-1.pdf", state: "ready", check: null, run_id: "run-1" },
        b: { unified: "2026-09-02_SZAMLA_Minta-Kft_datum.pdf", state: "review", check: "hiányzik: Számla sorszáma", run_id: "run-1" } },
    } as unknown as RunView;
    const run = vi.spyOn(api, "run").mockResolvedValue(view);
    vi.spyOn(api, "item").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "settings").mockReturnValue(new Promise(() => {}));
    render(<ReviewWorkspace wp={{ id: "wp-1" } as Workpackage} itemId="a" />);
    expect(await screen.findByText("2026-09-01_SZAMLA_Minta-Kft_A-1.pdf")).toBeTruthy();
    expect(run).toHaveBeenCalledWith("run-1", "unified");
    expect(screen.getByLabelText("Ellenőrzendő név: hiányzik: Számla sorszáma")).toBeTruthy();
    await userEvent.setup().type(screen.getByRole("searchbox", { name: "Tétel keresése" }), "scan_0002");
    await waitFor(() => expect(screen.queryByText("2026-09-01_SZAMLA_Minta-Kft_A-1.pdf")).toBeNull());
    expect(screen.getByText("2026-09-02_SZAMLA_Minta-Kft_datum.pdf")).toBeTruthy();
  });
});
