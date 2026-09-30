// 056 U1: behaviour of the unified data view — searchable picker, shared table (the request goes to the service:
// search, filter, sorting, paging), download panel (scope, columns), the data viewer's route.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsColumn, type DsPage, type DsQuery } from "./api";
import { cellText, DataTable, filterText, linkOf } from "./components/DataTable";
import { Picker } from "./components/Picker";
import { parseRoute, routeHash } from "./route";

const COLS: DsColumn[] = [
  { key: "file", label: "Irat", kind: "text", hidden: false, labels: null, link: "review" },
  { key: "field", label: "Mező", kind: "enum", hidden: false, labels: { gross_total: "Bruttó összeg", currency: "Pénznem" } },
  { key: "value", label: "Érték", kind: "money", hidden: false, labels: null },
  { key: "item_id", label: "Tétel-azonosító", kind: "id", hidden: true, labels: null },
];

function page(query: DsQuery, total = 3): DsPage {
  const rows = [
    { _key: "a:gross_total", _wp: "wp-1", _run: "run-1", file: "a.pdf", field: "gross_total", value: "12583.00", item_id: "a" },
    { _key: "b:gross_total", _wp: "wp-1", _run: "run-1", file: "b.pdf", field: "gross_total", value: "9908", item_id: "b" },
    { _key: "b:currency", _wp: "wp-1", _run: "run-1", file: "b.pdf", field: "currency", value: null, item_id: "b" },
  ].slice(query.offset ?? 0, (query.offset ?? 0) + (query.limit ?? 100));
  return {
    dataset: { name: "datapoints", label: "Adatpontok", scope: ["run_id"], optional_scope: [] }, columns: COLS, rows, total,
    matched: total, offset: query.offset ?? 0, limit: query.limit ?? 100, facets: { field: ["currency", "gross_total"] },
  };
}

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe("egységes választó", () => {
  const OPTS = [
    { value: "shadow", label: "Próba" }, { value: "apply", label: "Éles" }, { value: "x", label: "Számla-feldolgozás", detail: "v2" },
  ];

  it("mindig kereshető: ékezet nélkül is szűr, Enterrel választ", async () => {
    const onChange = vi.fn();
    render(<Picker label="Mód" value="shadow" options={OPTS} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: /Mód/ }));
    const search = screen.getByRole("combobox", { name: /Mód: keresés/ });
    await userEvent.type(search, "szamla");
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Számla-feldolgozásv2"]);
    await userEvent.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("x");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("billentyűzettel léptethető, Esc bezárja; gépelés a gombon azonnal keres", async () => {
    const onChange = vi.fn();
    render(<Picker label="Mód" value="shadow" options={OPTS} onChange={onChange} />);
    const trigger = screen.getByRole("button", { name: /Mód/ });
    trigger.focus();
    await userEvent.keyboard("É");
    expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe("É");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    await userEvent.click(trigger);
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("apply");
  });

  it("szolgáltatás oldali keresésnél a beírt szöveg a hívóhoz megy, a lista nem szűrődik helyben", async () => {
    const onSearch = vi.fn();
    render(<Picker label="Futás" value={null} options={OPTS} onChange={() => {}} onSearch={onSearch} more={40} />);
    await userEvent.click(screen.getByRole("button", { name: /Futás/ }));
    await userEvent.type(screen.getByRole("combobox"), "zzz");
    expect(onSearch).toHaveBeenLastCalledWith("zzz");
    expect(screen.getAllByRole("option")).toHaveLength(3);
    expect(screen.getByText(/még 40 találat/)).toBeTruthy();
  });
});

describe("közös táblázat", () => {
  it("a keresést, a rendezést, a szűrőt és a lapozást a szolgáltatástól kéri", async () => {
    const spy = vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q, 250));
    render(<DataTable dataset="datapoints" scope={{ run_id: "run-1" }} label="Adatpontok" />);
    expect(await screen.findByText("a.pdf")).toBeTruthy();
    expect(spy).toHaveBeenLastCalledWith("datapoints", { run_id: "run-1" }, expect.objectContaining({ offset: 0, limit: 100 }));
    expect(screen.getByRole("status").textContent).toContain("1–100 / 250 sor");

    await userEvent.click(screen.getByRole("button", { name: /^Mező/ }));
    await waitFor(() => expect(spy).toHaveBeenLastCalledWith("datapoints", expect.anything(), expect.objectContaining({ sort: [{ col: "field", desc: false }] })));

    await userEvent.click(screen.getByRole("button", { name: "Szűrő: Mező" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Bruttó összeg" }));
    await userEvent.click(screen.getByRole("button", { name: "Szűrés" }));
    await waitFor(() => expect(spy).toHaveBeenLastCalledWith("datapoints", expect.anything(),
      expect.objectContaining({ filters: [{ col: "field", op: "in", value: ["gross_total"] }], offset: 0 })));
    expect(screen.getByText("Mező: Bruttó összeg")).toBeTruthy(); // active filter with its label

    await userEvent.click(screen.getByRole("button", { name: "Következő lap" }));
    await waitFor(() => expect(spy).toHaveBeenLastCalledWith("datapoints", expect.anything(), expect.objectContaining({ offset: 100 })));

    await userEvent.type(screen.getByRole("searchbox"), "brutt");
    await waitFor(() => expect(spy).toHaveBeenLastCalledWith("datapoints", expect.anything(), expect.objectContaining({ q: "brutt", offset: 0 })));
  });

  it("058: a rendezhetőség minden fejlécen látszik, a rendezett oszlopon az irány; a súgó a következő kattintást mondja", async () => {
    vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q));
    const { container } = render(<DataTable dataset="datapoints" scope={{ run_id: "run-1" }} label="Adatpontok" />);
    await screen.findByText("a.pdf");
    const marks = () => [...container.querySelectorAll(".sort-mark")].map((m) => m.getAttribute("data-dir"));
    expect(marks()).toEqual(["none", "none", "none"]); // every visible column is sortable, none is sorted
    const head = screen.getByRole("button", { name: /^Mező/ });
    expect(head.getAttribute("title")).toContain("növekvő sorrend");
    await userEvent.click(head);
    await waitFor(() => expect(marks()).toEqual(["none", "asc", "none"]));
    expect(head.closest("th")?.getAttribute("aria-sort")).toBe("ascending");
    expect(head.getAttribute("title")).toContain("csökkenő sorrend");
    await userEvent.click(head);
    await waitFor(() => expect(marks()).toEqual(["none", "desc", "none"]));
  });

  it("felsorolt kód helyett felirat, pénz magyar írásmóddal, rejtett oszlop bekapcsolható és megmarad", async () => {
    localStorage.clear();
    vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q));
    const { unmount } = render(<DataTable dataset="datapoints" scope={{ run_id: "run-1" }} label="Adatpontok" />);
    const table = await screen.findByRole("table", { name: "Adatpontok" });
    expect(within(table).getAllByText("Bruttó összeg")).toHaveLength(2);
    expect(within(table).getByText(/12\s583/)).toBeTruthy();
    expect(within(table).queryByText("Tétel-azonosító")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Oszlopok \(3\/4\)/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Tétel-azonosító" }));
    expect(within(table).getByText("Tétel-azonosító")).toBeTruthy();
    unmount();
    render(<DataTable dataset="datapoints" scope={{ run_id: "run-1" }} label="Adatpontok" />);
    expect(await screen.findByRole("button", { name: /Oszlopok \(4\/4\)/ })).toBeTruthy();
    localStorage.clear();
  });

  it("a letöltés-panel a legszűkebb terjedelmet ajánlja, és a táblázat lekérdezésével kér fájlt", async () => {
    vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q));
    const dl = vi.spyOn(api, "datasetExport").mockResolvedValue({ filename: "datapoints-run-1-selected.xlsx", rows: 1 });
    render(<DataTable dataset="datapoints" scope={{ run_id: "run-1" }} label="Adatpontok" selectable />);
    await screen.findByText("a.pdf");
    await userEvent.click(screen.getAllByRole("checkbox", { name: "Sor kijelölése" })[1]);
    expect(screen.getByText("1 kijelölt sor")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Letöltés" }));
    const panel = screen.getByRole("dialog", { name: /Letöltés: Adatpontok/ });
    expect((within(panel).getByRole("radio", { name: /A kijelölt sorok \(1\)/ }) as HTMLInputElement).checked).toBe(true);
    expect((within(panel).getByRole("radio", { name: /A szűrt sorok/ }) as HTMLInputElement).disabled).toBe(true);
    await userEvent.click(within(panel).getByRole("radio", { name: /CSV/ }));
    await userEvent.click(within(panel).getByRole("button", { name: /Letöltés \(1 sor\)/ }));
    expect(dl).toHaveBeenCalledWith("datapoints", { run_id: "run-1" }, expect.objectContaining({
      format: "csv", rows: "selected", columns: ["file", "field", "value"], query: expect.objectContaining({ keys: ["b:gross_total"] }),
    }));
    expect(await within(panel).findByText(/Letöltve: datapoints-run-1-selected.xlsx \(1 sor\)/)).toBeTruthy();
  });

  it("hivatkozás, felirat és szűrő-szöveg a cellákhoz", () => {
    const row = { _key: "a:x", _wp: "wp-1", _run: "run-1", item_id: "a" };
    expect(linkOf(COLS[0], row)).toBe("#/workpackages/wp-1/review/a");
    expect(linkOf({ ...COLS[0], link: "next" }, { ...row, _stage: "result" })).toBe("#/workpackages/wp-1/result");
    expect(linkOf({ ...COLS[0], link: "run" }, row)).toBe("#/runs/run-1");
    expect(cellText(COLS[1], "currency")).toBe("Pénznem");
    expect(filterText({ col: "value", op: "gte", value: "12000" }, COLS[2])).toMatch(/^Érték ≥ 12\s000$/);
    expect(filterText({ col: "file", op: "contains", value: "elmu" }, COLS[0])).toBe("Irat tartalmazza „elmu”");
  });
});

describe("útvonalak (057)", () => {
  it("a csomag szakaszai, az eredmény táblája és futása a címsorban; a régi címek az új helyre visznek", () => {
    const h = routeHash({ view: "workpackages", wpId: "wp-1", stage: "result", table: "line_items", runId: "run-000000000001" });
    expect(h).toBe("#/workpackages/wp-1/result/line_items?run=run-000000000001");
    expect(parseRoute(h)).toEqual({ view: "workpackages", wpId: "wp-1", stage: "result", table: "line_items", runId: "run-000000000001" });
    expect(parseRoute("#/workpackages/wp-1")).toEqual({ view: "workpackages", wpId: "wp-1", stage: undefined });
    expect(parseRoute("#/workpackages/wp-1/items")).toMatchObject({ stage: "review" }); // old Tételek (Items) tab
    expect(parseRoute("#/workpackages/wp-1/workflow")).toMatchObject({ stage: "process" }); // old Folyamat (Workflow) tab
    expect(parseRoute("#/data/datapoints?run_id=run-1")).toEqual({ view: "legacy-result", runId: "run-1", table: "datapoints" });
    expect(parseRoute("#/runs")).toEqual({ view: "settings", section: "system" });
    expect(parseRoute("#/runs/run-1")).toEqual({ view: "run", runId: "run-1" });
    expect(parseRoute("#/settings/nincs")).toEqual({ view: "settings", section: "mailboxes" });
  });
});
