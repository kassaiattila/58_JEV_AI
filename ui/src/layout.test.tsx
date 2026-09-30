// 057: a felület új szerkezete — a csomag a következő lépés szakaszánál nyílik, a szakaszok a saját állapotukkal,
// a fejléc gombja a szolgáltatás által számolt következő lépés.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsPage, type WorkpackageView } from "./api";
import { stageStatus, WorkpackageDetail } from "./views/WorkpackageDetail";

function view(over: Partial<WorkpackageView> = {}): WorkpackageView {
  return {
    workpackage: {
      id: "wp-1", name: "Közmű minta", source_kind: "manual", source_ref: null, revision: 1, status: "open", created_at: "2026-09-28T10:00:00Z",
      updated_at: "2026-09-28T10:00:00Z", items: [{ item_id: "a", kind: "document", source_path: "C:/x/a.pdf", sha256: "a", added_revision: 1 }],
      assignment: { workpackage_id: "wp-1", revision: 1, recipe_id: "document-processing", recipe_version: 2, recipe_hash: "h", params: { arm: "auto" },
        actor: "Teszt Elek", note: null, created_at: "2026-09-28T10:00:00Z" },
    },
    readiness: { workpackage_id: "wp-1", ready: true, blockers: [], warnings: [], counts: { items: 1 }, budget: { jev: "0.1" }, assignment_revision: 1, input_hash: "0123456789abcdef" },
    next: { code: "start", label: "Próbafutás indítása", stage: "process" }, last_run: null, runs: 0,
    ...over,
  };
}

const EMPTY: DsPage = {
  dataset: { name: "runs", label: "Futások", scope: [], optional_scope: ["workpackage_id"] }, columns: [], rows: [], total: 0, matched: 0,
  offset: 0, limit: 50, facets: {},
};

afterEach(() => vi.restoreAllMocks());

describe("munkacsomag szakaszai", () => {
  it("cím nélkül a következő lépés szakaszánál nyílik; a szakaszok állapottal, a fejléc gombja a következő lépés", async () => {
    vi.spyOn(api, "workpackage").mockResolvedValue(view());
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    render(<WorkpackageDetail wpId="wp-1" route={{ view: "workpackages", wpId: "wp-1" }} />);
    const tabs = await screen.findByRole("tablist", { name: "A csomag szakaszai" });
    const selected = within(tabs).getAllByRole("tab").find((t) => t.getAttribute("aria-selected") === "true");
    expect(selected?.textContent).toContain("Feldolgozás");
    expect(within(tabs).getByRole("tab", { name: /Feldolgozás.*indítható/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Próbafutás indítása/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Újrafuttatás…" }).hasAttribute("disabled")).toBe(true); // nincs mit megismételni
  });

  it("a szakaszok állapota a legutóbbi futásból", () => {
    const run = { run_id: "run-000000000001", workpackage_id: "wp-1", workpackage_name: "x", recipe_id: "r", recipe_version: 1, mode: "shadow" as const,
      status: "needs_review", approval: null, approved_by: null, actor: "a", created_at: "", finished_at: null, items: 49, items_done: 49, open_reasons: 53 };
    const st = stageStatus(view({ last_run: run, runs: 1 }));
    expect(st.process).toBe("Próba · teendő vár · 49/49");
    expect(st.review).toBe("53 teendő");
    expect(st.result).toBe("próba-eredmény");
    expect(stageStatus(view({ last_run: { ...run, mode: "apply", status: "done", open_reasons: 0, approval: "approved" }, runs: 1 })).result).toBe("kiadva");
  });
});

describe("a csomag kezelése (058)", () => {
  it("postafiók-csomagnál „levél”, vegyesnél mindkettő a fejlécben", async () => {
    const mail = { item_id: "m", kind: "email", source_path: "C:/inbox/m/message.json", sha256: "m", added_revision: 1 };
    const doc = view().workpackage.items[0];
    vi.spyOn(api, "workpackage").mockResolvedValue(view({ workpackage: { ...view().workpackage, items: [mail, { ...mail, item_id: "n" }] } }));
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    const { unmount } = render(<WorkpackageDetail wpId="wp-1" route={{ view: "workpackages", wpId: "wp-1" }} />);
    expect((await screen.findAllByText(/^2 levél/)).length).toBe(2); // fejléc + az Ellenőrzés szakasz állapota
    unmount();
    vi.spyOn(api, "workpackage").mockResolvedValue(view({ workpackage: { ...view().workpackage, items: [mail, doc] } }));
    render(<WorkpackageDetail wpId="wp-1" route={{ view: "workpackages", wpId: "wp-1" }} />);
    expect((await screen.findAllByText(/^1 irat, 1 levél/)).length).toBe(2);
  });

  it("elrejtés és törlés: futás nélkül törölhető megerősítéssel, futással csak elrejthető", async () => {
    vi.spyOn(api, "workpackage").mockResolvedValue(view());
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    const archive = vi.spyOn(api, "archiveWorkpackage").mockResolvedValue(view());
    const del = vi.spyOn(api, "deleteWorkpackage").mockResolvedValue({ deleted: "wp-1" });
    const user = userEvent.setup();
    render(<WorkpackageDetail wpId="wp-1" route={{ view: "workpackages", wpId: "wp-1" }} />);
    await user.click(await screen.findByRole("button", { name: "Csomag kezelése" }));
    await user.click(screen.getByRole("button", { name: "Végleges törlés…" }));
    expect(del).not.toHaveBeenCalled(); // előbb megerősítés
    await user.click(screen.getByRole("button", { name: "Végleges törlés" }));
    expect(del).toHaveBeenCalledWith("wp-1");
    await user.click(screen.getByRole("button", { name: "Csomag kezelése" }));
    await user.click(screen.getByRole("button", { name: "Elrejtés a listából" }));
    expect(archive).toHaveBeenCalledWith("wp-1");
  });

  it("futással rendelkező csomagnál nincs törlés, elrejtett csomagnál visszahozás és jelzés", async () => {
    const hidden = view({ runs: 2, workpackage: { ...view().workpackage, status: "archived" } });
    vi.spyOn(api, "workpackage").mockResolvedValue(hidden);
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    const user = userEvent.setup();
    render(<WorkpackageDetail wpId="wp-1" route={{ view: "workpackages", wpId: "wp-1", stage: "result" }} />);
    expect(await screen.findByText(/el van rejtve a listából/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Csomag kezelése" }));
    expect(screen.getByRole("button", { name: "Visszahozás a listába" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Végleges törlés…" })).toBeNull();
  });
});

describe("Feldolgozás szakasz (058 D)", () => {
  it("egyetlen kiemelt futás-gomb a következő lépés szerint; a költségkeret két tizedessel, szolgáltatónévvel", async () => {
    const run = { run_id: "run-000000000001", workpackage_id: "wp-1", workpackage_name: "x", recipe_id: "r", recipe_version: 1, mode: "shadow" as const,
      status: "done", approval: null, approved_by: null, actor: "a", created_at: "", finished_at: null, items: 1, items_done: 1, open_reasons: 0 };
    vi.spyOn(api, "workpackage").mockResolvedValue(view({ last_run: run, runs: 1, next: { code: "go_live", label: "Próba rendben: éles futás", stage: "process" },
      readiness: { ...view().readiness, budget: { jev: "2.03", openai: "2.9" } } }));
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    render(<WorkpackageDetail wpId="wp-1" route={{ view: "workpackages", wpId: "wp-1", stage: "process" }} />);
    const live = await screen.findByRole("button", { name: "Éles futás…" });
    expect(live.className).toBe("primary");
    expect(screen.getByRole("button", { name: "Próbafutás…" }).className).toBe("secondary");
    expect(screen.getByRole("button", { name: "Újrafuttatás…" }).className).toBe("secondary");
    expect(screen.getByText(/JEV legfeljebb 2,03 USD, OpenAI legfeljebb 2,90 USD/)).toBeTruthy();
  });
});

describe("futás indítása megerősítéssel (061)", () => {
  it("a gomb nem indít, hanem a megerősítő oldalra visz; ott az összegzés, indítás csak onnan, a Mégse visszavisz", async () => {
    const user = userEvent.setup();
    const start = vi.spyOn(api, "start").mockResolvedValue({ run_id: "run-000000000009", deduped: false } as Awaited<ReturnType<typeof api.start>>);
    vi.spyOn(api, "workpackage").mockResolvedValue(view({ readiness: { ...view().readiness, budget: { jev: "0.1", openai: "0.25" } } }));
    vi.spyOn(api, "readiness").mockResolvedValue({ ...view().readiness, budget: { jev: "0.1", openai: "0.25" } });
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    window.location.hash = "#/workpackages/wp-1/process";
    const { unmount } = render(<WorkpackageDetail wpId="wp-1" route={{ view: "workpackages", wpId: "wp-1", stage: "process" }} />);
    await user.click(await screen.findByRole("button", { name: "Próbafutás…" }));
    expect(start).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("#/workpackages/wp-1/process/start?mode=shadow");
    unmount();

    render(<WorkpackageDetail wpId="wp-1" route={{ view: "workpackages", wpId: "wp-1", stage: "process", start: { mode: "shadow", rerun: false } }} />);
    const page = await screen.findByRole("region", { name: "Próbafutás indításának megerősítése" });
    expect(within(page).getByText("Közmű minta")).toBeTruthy();
    expect(within(page).getByText("1 tétel")).toBeTruthy();
    expect(within(page).getByText(/JEV legfeljebb 0,10 USD, OpenAI legfeljebb 0,25 USD/)).toBeTruthy();
    expect(within(page).getByText(/fizetős hívásokkal jár/)).toBeTruthy();
    await user.click(within(page).getByRole("button", { name: "Mégse" }));
    expect(window.location.hash).toBe("#/workpackages/wp-1/process");
    expect(start).not.toHaveBeenCalled();
    await waitFor(() => expect(within(page).getByRole("button", { name: "Próbafutás indítása" }).hasAttribute("disabled")).toBe(false));
    await user.click(within(page).getByRole("button", { name: "Próbafutás indítása" }));
    expect(start).toHaveBeenCalledWith("wp-1", { mode: "shadow", expected_revision: 1, input_hash: "0123456789abcdef" });
    expect(window.location.hash).toBe("#/runs/run-000000000009");
  });

  it("nem indítható csomagnál az indítás tiltva, az akadály látszik", async () => {
    vi.spyOn(api, "workpackage").mockResolvedValue(view({ readiness: { ...view().readiness, ready: false, blockers: [{ code: "no_items", message: "nincs tétel" }] } }));
    vi.spyOn(api, "readiness").mockResolvedValue({ ...view().readiness, ready: false, blockers: [{ code: "no_items", message: "nincs tétel" }] });
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    render(<WorkpackageDetail wpId="wp-1" route={{ view: "workpackages", wpId: "wp-1", stage: "process", start: { mode: "apply", rerun: false } }} />);
    const page = await screen.findByRole("region", { name: "Éles futás indításának megerősítése" });
    expect(within(page).getByRole("button", { name: "Éles futás indítása" }).hasAttribute("disabled")).toBe(true);
  });
});
