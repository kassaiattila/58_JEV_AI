// 089 (the owner's decision of 2026-10-02): the use of JEV is the first processing setting; without JEV every document
// runs on the G path, so the path and the JEV answers do not count: they are not shown, one sentence stands instead
// (settings card, editor, confirmation page, run summary). Artificial data, no service.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsPage, type Readiness, type Recipe, type RecipeHelp, type WorkpackageView } from "./api";
import { jevOffNote, orderedParams, paramInEffect, paramsText } from "./labels";
import { ProcessStage } from "./views/ProcessStage";
import { RecipeParamList, RecipesPanel } from "./views/RecipeInfo";
import { StartConfirm } from "./views/StartConfirm";

afterEach(() => vi.restoreAllMocks());

const NOTE = "JEV nélkül minden irat a G-úton fut (a GPT olvassa ki az adatokat, a kód ellenőrzi őket), ezért az út és a JEV-válaszok beállítása nem számít, és nem látszik.";

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

const HELP: RecipeHelp = { intro: "Bevezető.", kinds: {}, recipes: {}, params: {} };
const EMPTY: DsPage = {
  dataset: { name: "runs", label: "Futások", scope: [], optional_scope: ["workpackage_id"] }, columns: [], rows: [], total: 0, matched: 0,
  offset: 0, limit: 50, facets: {},
};

describe("089 settings that only count with JEV", () => {
  it("puts the use of JEV first and keeps the recipe's order for the rest", () => {
    expect(orderedParams(["arm", "jev_cache", "tasks", "azure_ocr", "jev"])).toEqual(["jev", "arm", "jev_cache", "tasks", "azure_ocr"]);
    expect(orderedParams(["arm", "azure_ocr"])).toEqual(["arm", "azure_ocr"]);
  });

  it("drops the path and the JEV answers without JEV; an assignment from before the switch ran with JEV", () => {
    const off = { arm: "S", jev_cache: "live", tasks: "off", jev: "off" };
    expect(paramInEffect("arm", off)).toBe(false);
    expect(paramInEffect("jev_cache", off)).toBe(false);
    expect(paramInEffect("tasks", off)).toBe(true);
    expect(paramInEffect("arm", { arm: "S" })).toBe(true);
    expect(paramsText(off)).toBe("JEV használata: kikapcsolva — csak GPT (OpenAI) · Feladatjavaslat: kikapcsolva");
    expect(jevOffNote(off)).toBe(NOTE);
    expect(jevOffNote({ jev: "on" })).toBeNull();
  });

  it("the settings card shows the use of JEV first and one sentence instead of the path", () => {
    const { container } = render(<RecipeParamList recipe={PROCESSING} params={{ jev: "off" }} help={HELP} kinds={["document"]} />);
    expect(container.querySelector("dt")?.textContent).toBe("JEV használata");
    expect(screen.queryByText("Út")).toBeNull();
    expect(screen.queryByText("JEV-válaszok")).toBeNull();
    expect(screen.getByText(NOTE)).toBeTruthy();
  });

  it("with JEV on, the path is shown and there is no sentence", () => {
    render(<RecipeParamList recipe={PROCESSING} params={{}} help={HELP} kinds={["document"]} />);
    expect(screen.getByText("Út")).toBeTruthy();
    expect(screen.queryByText(NOTE)).toBeNull();
  });

  it("the confirmation page lists the settings that count, the use of JEV first", async () => {
    const v = view({ arm: "S", jev_cache: "reuse", tasks: "off", azure_ocr: "on", jev: "off" });
    vi.spyOn(api, "readiness").mockResolvedValue(v.readiness);
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [PROCESSING], help: HELP });
    render(<StartConfirm view={v} mode="shadow" rerun={false} onChanged={() => {}} />);
    await waitFor(() => expect(screen.getByText(NOTE)).toBeTruthy());
    const items = within(screen.getByText(NOTE).closest("ul") as HTMLElement).getAllByRole("listitem").map((li) => li.textContent);
    expect(items[0]).toMatch(/^JEV használata: Kikapcsolva/);
    expect(items.some((x) => x?.startsWith("Út:"))).toBe(false);
    expect(items.some((x) => x?.startsWith("JEV-válaszok:"))).toBe(false);
  });

  it("the confirmation page shows a setting missing from an older assignment with its default", async () => {
    const v = view({ arm: "auto", jev_cache: "reuse", tasks: "off", azure_ocr: "on" });
    vi.spyOn(api, "readiness").mockResolvedValue(v.readiness);
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [PROCESSING], help: HELP });
    render(<StartConfirm view={v} mode="shadow" rerun={false} onChanged={() => {}} />);
    await waitFor(() => expect(screen.getByText(/^JEV használata: Bekapcsolva/)).toBeTruthy());
    expect(screen.getByText(/^Út: Automatikus/)).toBeTruthy();
    expect(screen.queryByText(NOTE)).toBeNull();
  });

  it("in the editor, switching JEV off hides the path and the JEV answers", async () => {
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [PROCESSING], help: HELP });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    render(<ProcessStage view={view({ arm: "auto", jev_cache: "reuse", tasks: "off", azure_ocr: "on", jev: "on" })} onChanged={() => {}} />);
    const editor = await screen.findByRole("button", { name: "Módosítás" });
    await waitFor(() => expect((editor as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(editor);
    const form = await waitFor(() => document.querySelector(".recipe-form") as HTMLElement);
    const labels = () => [...form.querySelectorAll(".param-field")].map((f) => f.querySelector("button")?.getAttribute("aria-label") ?? f.textContent);
    expect(within(form).getByRole("button", { name: "Út" })).toBeTruthy();
    expect(labels()[0]).toMatch(/JEV használata/);
    fireEvent.click(within(form).getByRole("button", { name: "JEV használata" }));
    fireEvent.click(await screen.findByRole("option", { name: /^Kikapcsolva/ }));
    await waitFor(() => expect(within(form).queryByRole("button", { name: "Út" })).toBeNull());
    expect(within(form).queryByRole("button", { name: "JEV-válaszok" })).toBeNull();
    expect(within(form).getByText(NOTE)).toBeTruthy();
  });
});

describe("089 Settings › Processing", () => {
  it("describes the use of JEV first, with the sentence at its off value", async () => {
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [PROCESSING], help: HELP });
    const { container } = render(<RecipesPanel />);
    await screen.findByText("Beállítások");
    expect(container.querySelector(".param-doc strong")?.textContent).toBe("JEV használata");
    expect(screen.getAllByText(NOTE)).toHaveLength(1);
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
