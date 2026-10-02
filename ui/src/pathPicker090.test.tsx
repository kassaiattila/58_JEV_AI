// 090 (the owner's trial and decision of 2026-10-02: "one picker, four paths"): the path and the use of JEV are one
// choice, "Feldolgozási út": automatic, JEV where possible (S), GPT + JEV (G), or GPT only, without JEV. The saved
// settings keep their two values (the path and the use of JEV), so packages, runs and measurements stay as they are.
// The earlier answers count on every path (JEV and GPT alike). A package of emails only chooses between "with JEV"
// and "GPT only".
// Replaces the 089 tests of the separate switch. Artificial data, no service.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsPage, type Readiness, type Recipe, type RecipeHelp, type WorkpackageView } from "./api";
import { applyPath, paramsText, pathOptions, pathValue, shownParams } from "./labels";
import { ProcessStage } from "./views/ProcessStage";
import { RecipeParamList, RecipesPanel } from "./views/RecipeInfo";
import { StartConfirm } from "./views/StartConfirm";

afterEach(() => vi.restoreAllMocks());

const PROCESSING: Recipe = {
  id: "processing", version: 1, status: "active", title: "Feldolgozás", description: "Leírás.", steps: [], requirements: [],
  result: "Eredmény.", manual_action: "Teendők.",
  params: { arm: { allowed: ["auto", "S", "G"], default: "auto" }, jev_cache: { allowed: ["reuse", "live"], default: "reuse" },
    tasks: { allowed: ["off", "propose"], default: "off" }, azure_ocr: { allowed: ["on", "off"], default: "on" },
    jev: { allowed: ["on", "off"], default: "on" } },
  max_item_usd: { auto: { jev: "0.07", openai: "0.15" } },
  max_item_usd_by_kind: { email: { "*": { jev: "0.05" } }, document: { auto: { jev: "0.07", openai: "0.15" } } },
  param_item_usd: [{ param: "jev", value: "off", kind: "document", usd: { openai: "0.07" }, drop: ["jev"] }],
};

const HELP: RecipeHelp = {
  intro: "Bevezető.", kinds: {}, recipes: {},
  params: { path: { help: "Melyik eszköz dolgozzon.", options: { auto: "Az ajánlott út.", S: "S-út.", G: "G-út.", gpt: "Csak GPT magyarázat.", jev: "JEV-vel magyarázat." } } },
};
const EMPTY: DsPage = {
  dataset: { name: "runs", label: "Futások", scope: [], optional_scope: ["workpackage_id"] }, columns: [], rows: [], total: 0, matched: 0,
  offset: 0, limit: 50, facets: {},
};
const KEYS = ["arm", "jev_cache", "tasks", "azure_ocr", "jev"];

describe("090 the processing path: one choice", () => {
  it("shows one path in place of the path and the use of JEV, then the settings that count", () => {
    expect(shownParams(KEYS, { jev: "on" }, ["document", "email"])).toEqual(["path", "jev_cache", "tasks", "azure_ocr"]);
    expect(shownParams(KEYS, { jev: "off" }, ["document", "email"])).toEqual(["path", "jev_cache", "tasks", "azure_ocr"]);  // GPT reuses too
    expect(shownParams(KEYS, {}, ["document"])).toEqual(["path", "jev_cache", "azure_ocr"]);  // an older assignment ran with JEV
    expect(shownParams(["arm", "azure_ocr"], {}, ["document"])).toEqual(["arm", "azure_ocr"]);  // a recipe without the switch
  });

  it("maps the four paths onto the saved values, and back", () => {
    expect(pathValue({ arm: "S", jev: "on" })).toBe("S");
    expect(pathValue({ arm: "S", jev: "off" })).toBe("gpt");
    expect(pathValue({ arm: "G" })).toBe("G");
    expect(pathValue({})).toBe("auto");
    expect(applyPath({ arm: "S", jev: "on", tasks: "off" }, "gpt")).toEqual({ arm: "S", jev: "off", tasks: "off" });
    expect(applyPath({ arm: "S", jev: "off" }, "G")).toEqual({ arm: "G", jev: "on" });
    expect(pathOptions(["auto", "S", "G"], ["document"])).toEqual(["auto", "S", "G", "gpt"]);
  });

  it("a package of emails only chooses between JEV and GPT only (the documents' path does not act on it)", () => {
    expect(pathOptions(["auto", "S", "G"], ["email"])).toEqual(["jev", "gpt"]);
    expect(pathValue({ arm: "S", jev: "on" }, ["email"])).toBe("jev");
    expect(pathValue({ arm: "S", jev: "off" }, ["email"])).toBe("gpt");
    expect(applyPath({ arm: "S", jev: "off" }, "jev")).toEqual({ arm: "S", jev: "on" });
  });

  it("the run summary names the path once", () => {
    expect(paramsText({ arm: "S", jev_cache: "live", tasks: "off", jev: "off" })).toBe("Feldolgozási út: Csak GPT, JEV nélkül (OpenAI) · Korábbi válaszok: mindig élő hívás · Feladatjavaslat: kikapcsolva");
    expect(paramsText({ arm: "G", jev_cache: "reuse", jev: "on" })).toBe("Feldolgozási út: GPT + JEV — tételsorokkal (G) · Korábbi válaszok: korábbi válasz újrahasználható");
  });

  it("the settings card shows the path first, with its explanation, and no separate use of JEV", () => {
    const { container } = render(<RecipeParamList recipe={PROCESSING} params={{ jev: "off" }} help={HELP} kinds={["document"]} />);
    expect(container.querySelector("dt")?.textContent).toBe("Feldolgozási út");
    expect(screen.getByText("Csak GPT, JEV nélkül (OpenAI)")).toBeTruthy();
    expect(screen.getByText("Csak GPT magyarázat.")).toBeTruthy();
    for (const gone of ["JEV használata", "Út", "JEV-válaszok"]) expect(screen.queryByText(gone)).toBeNull();
  });

  it("the confirmation page lists the path first and only the settings that count", async () => {
    const v = view({ arm: "S", jev_cache: "reuse", tasks: "off", azure_ocr: "on", jev: "off" });
    vi.spyOn(api, "readiness").mockResolvedValue(v.readiness);
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [PROCESSING], help: HELP });
    render(<StartConfirm view={v} mode="shadow" rerun={false} onChanged={() => {}} />);
    const first = await screen.findByText(/^Feldolgozási út: Csak GPT, JEV nélkül/);
    const items = within(first.closest("ul") as HTMLElement).getAllByRole("listitem").map((li) => li.textContent ?? "");
    expect(items[0]).toBe(first.textContent);
    expect(items.some((x) => /^(Út|JEV használata|JEV-válaszok):/.test(x))).toBe(false);
  });

  it("the confirmation page shows an older assignment's path with JEV", async () => {
    const v = view({ arm: "auto", jev_cache: "reuse", tasks: "off", azure_ocr: "on" });
    vi.spyOn(api, "readiness").mockResolvedValue(v.readiness);
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [PROCESSING], help: HELP });
    render(<StartConfirm view={v} mode="shadow" rerun={false} onChanged={() => {}} />);
    await waitFor(() => expect(screen.getByText(/^Feldolgozási út: Automatikus/)).toBeTruthy());
    expect(screen.getByText(/^Korábbi válaszok:/)).toBeTruthy();
  });

  it("in the editor, one picker offers the four paths; GPT only keeps the earlier answers and saves the use of JEV off", async () => {
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [PROCESSING], help: HELP });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    const save = vi.spyOn(api, "saveWorkflow").mockResolvedValue({} as never);
    render(<ProcessStage view={view({ arm: "S", jev_cache: "reuse", tasks: "off", azure_ocr: "on", jev: "on" })} onChanged={() => {}} />);
    const editor = await screen.findByRole("button", { name: "Módosítás" });
    await waitFor(() => expect((editor as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(editor);
    const form = await waitFor(() => document.querySelector(".recipe-form") as HTMLElement);
    expect(within(form).queryByRole("button", { name: "JEV használata" })).toBeNull();
    expect(within(form).queryByRole("button", { name: "Út" })).toBeNull();
    expect(within(form).getByRole("button", { name: "Korábbi válaszok" })).toBeTruthy();
    fireEvent.click(within(form).getByRole("button", { name: "Feldolgozási út" }));
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent ?? "");
    expect(options).toHaveLength(4);
    expect(options[3]).toMatch(/^Csak GPT, JEV nélkül/);
    fireEvent.click(screen.getByRole("option", { name: /^Csak GPT, JEV nélkül/ }));
    await waitFor(() => expect(within(form).getByText("Csak GPT magyarázat.")).toBeTruthy());
    expect(within(form).getByRole("button", { name: "Korábbi válaszok" })).toBeTruthy();
    fireEvent.click(within(form).getByRole("button", { name: "Beállítások mentése" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save.mock.calls[0][1].params).toMatchObject({ arm: "S", jev: "off", jev_cache: "reuse" });
  });
});

describe("090 Settings › Processing", () => {
  it("describes the four paths under one heading, without a separate use of JEV", async () => {
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [PROCESSING], help: HELP });
    const { container } = render(<RecipesPanel />);
    await screen.findByText("Beállítások");
    const headings = [...container.querySelectorAll(".param-doc > p > strong")].map((s) => s.textContent);
    expect(headings[0]).toBe("Feldolgozási út");
    expect(headings).not.toContain("JEV használata");
    expect(headings).not.toContain("Út");
    expect(screen.getByText("Csak GPT magyarázat.")).toBeTruthy();
  });
});

function view(params: Record<string, string>): WorkpackageView {
  const readiness: Readiness = {
    workpackage_id: "wp-1", ready: true, blockers: [], warnings: [], counts: { items: 1 }, budget: { openai: "0.22" },
    assignment_revision: 1, input_hash: "0123456789abcdef", assignment_default: false,
  };
  return {
    workpackage: {
      id: "wp-1", name: "Minta", source_kind: "manual", source_ref: null, revision: 1, status: "open", created_at: "2026-10-02T10:00:00Z",
      updated_at: "2026-10-02T10:00:00Z", items: [{ item_id: "a", kind: "document", source_path: "C:/x/a.pdf", sha256: "a", added_revision: 1 }],
      assignment: { workpackage_id: "wp-1", revision: 1, recipe_id: "processing", recipe_version: 1, recipe_hash: "h", params, actor: "teszt",
        note: null, created_at: "2026-10-02T10:00:00Z" },
    },
    readiness, next: { code: "start", label: "Próbafutás indítása", stage: "process" }, last_run: null, runs: 0,
  };
}
