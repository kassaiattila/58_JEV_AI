// 080 (the owner's decisions of 2026-10-01): one processing with processing settings. The pre-start overview names
// each service a run may call with the budget and what it is for; a package without saved settings starts with the
// default ones; the Settings › Processing page compares the S and G paths. Artificial data, no service.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Readiness, type Recipe, type RecipeHelp, type RunPlan, type WorkpackageView } from "./api";
import { paramShort, planLines, stepLabel } from "./labels";
import { RecipesPanel } from "./views/RecipeInfo";
import { StartConfirm } from "./views/StartConfirm";

afterEach(() => vi.restoreAllMocks());

const PLAN: RunPlan = { documents: 3, emails: 1, attachments: 0, paths: { S: 1, G: 1, unknown: 1 }, tasks_emails: 1, azure: true, jev_reuse: true };

const PROCESSING: Recipe = {
  id: "processing", version: 1, status: "active", title: "Feldolgozás", description: "Leírás.", steps: ["Beolvasás (szükség esetén szövegfelismerés)"],
  requirements: ["Legalább egy PDF-irat vagy levél a munkacsomagban"], result: "Eredmény.", manual_action: "Teendők.",
  params: { arm: { allowed: ["auto", "S", "G"], default: "auto" }, jev_cache: { allowed: ["reuse", "live"], default: "reuse" },
    tasks: { allowed: ["off", "propose"], default: "off" }, azure_ocr: { allowed: ["on", "off"], default: "on" } },
  max_item_usd: { S: { jev: "0.07", openai: "0.15" }, G: { jev: "0.07", openai: "0.15" }, auto: { jev: "0.07", openai: "0.15" } },
  max_item_usd_by_kind: { email: { "*": { jev: "0.05" } }, document: { auto: { jev: "0.07", openai: "0.15" } } },
};

const HELP: RecipeHelp = {
  intro: "A rendszer a csomag minden tételét a fajtája szerint dolgozza fel.",
  kinds: { document: "PDF-irat: a rendszer előbb felismeri a típusát.", email: "Levél: a rendszer felismeri, mi a levél célja." },
  recipes: {},
  paths: {
    intro: "Az út azt mondja meg, hogyan olvassa ki a rendszer az adatokat.", measured: "A számok forrása: az etalon.",
    columns: { S: "S-út: csak JEV", G: "G-út: GPT + JEV" },
    rows: [{ label: "Tételsorok", S: "Nem olvassa ki.", G: "Kiolvassa." }],
  },
  params: {},
};

describe("080 indítás előtti áttekintés", () => {
  it("szolgáltatónként a keretet és az okát mondja", () => {
    const lines = planLines(PLAN, { jev: "0.26", openai: "0.306", azure_di: "0.06" });
    expect(lines).toEqual([
      "Helyi szövegfelismerés: ingyenes, minden iraton.",
      "JEV legfeljebb 0,26 USD: 3 irat típusfelismerése és adatkinyerése; 1 levél szándékfelismerése; a korábban már feltett kérdésekért nem kell újra fizetni.",
      "OpenAI legfeljebb 0,31 USD: 1 irat a G-úton; 1 még ismeretlen típusú irat, ha a felismert típus a G-utat kéri; 1 levél feladatjavaslata.",
      "Azure DI legfeljebb 0,06 USD: csak gyenge minőségű szkennelésnél, a helyi felismerés helyett.",
    ]);
  });

  it("a nem hívott szolgáltatót is megnevezi", () => {
    const sOnly: RunPlan = { ...PLAN, emails: 0, tasks_emails: 0, paths: { S: 3, G: 0, unknown: 0 }, azure: false, jev_reuse: false };
    const lines = planLines(sOnly, { jev: "0.21" });
    expect(lines).toContain("OpenAI: nem hívódik, minden irat az S-úton fut.");
    expect(lines).toContain("Azure DI: nem hívódik (kikapcsolva).");
    expect(lines[1]).toMatch(/minden kérdés élő hívás/);
  });

  it("az út a beszédes nevét kapja, és nincs „recept kiválasztása” lépés", () => {
    expect(paramShort("arm", "auto")).toBe("Automatikus (ajánlott)");
    expect(paramShort("arm", "S")).toBe("Csak JEV — tételsorok nélkül, olcsóbb (S)");
    expect(paramShort("arm", "G")).toBe("GPT + JEV — tételsorokkal (G)");
    expect(stepLabel("configure", undefined, "configure")).toBe("configure"); // the service no longer sends this step
  });
});

describe("080 alapbeállítás és megerősítés", () => {
  it("mentett beállítás nélkül az alapbeállítást és az áttekintést mutatja", async () => {
    const v = view();
    vi.spyOn(api, "readiness").mockResolvedValue(v.readiness);
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [PROCESSING], help: HELP });
    render(<StartConfirm view={v} mode="shadow" rerun={false} onChanged={() => {}} />);
    expect(await screen.findByText("alapbeállítás, az indításkor mentődik a csomaghoz")).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/Út: Automatikus \(ajánlott\)/)).toBeTruthy());
    expect(screen.getByRole("heading", { name: "Mi történik indításkor" })).toBeTruthy();
    expect(screen.getByText(/1 irat típusfelismerése és adatkinyerése/)).toBeTruthy();
    expect(screen.queryByText("Recept")).toBeNull();
  });
});

describe("080 Beállítások › Feldolgozás", () => {
  it("a tételfajtákat és az utak összevetését mutatja", async () => {
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [PROCESSING], help: HELP });
    render(<RecipesPanel />);
    expect(await screen.findByText("PDF-irat: a rendszer előbb felismeri a típusát.")).toBeTruthy();
    expect(screen.getByText("Levél: a rendszer felismeri, mi a levél célja.")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "S-út: csak JEV" })).toBeTruthy();
    expect(screen.getByRole("rowheader", { name: "Tételsorok" })).toBeTruthy();
    expect(screen.getByText("Kiolvassa.")).toBeTruthy();
  });
});

function view(): WorkpackageView {
  const readiness: Readiness = {
    workpackage_id: "wp-1", ready: true, blockers: [], warnings: [], counts: { items: 1 }, budget: { jev: "0.07", openai: "0.15", azure_di: "0.02" },
    assignment_revision: 0, input_hash: "0123456789abcdef", assignment_default: true,
    plan: { documents: 1, emails: 0, attachments: 0, paths: { S: 0, G: 0, unknown: 1 }, tasks_emails: 0, azure: true, jev_reuse: true },
  };
  return {
    workpackage: {
      id: "wp-1", name: "Minta", source_kind: "manual", source_ref: null, revision: 1, status: "open", created_at: "2026-10-01T10:00:00Z",
      updated_at: "2026-10-01T10:00:00Z", items: [{ item_id: "a", kind: "document", source_path: "C:/x/a.pdf", sha256: "a", added_revision: 1 }],
      assignment: null,
    },
    readiness, next: { code: "start", label: "Próbafutás indítása", stage: "process" }, last_run: null, runs: 0,
  };
}
