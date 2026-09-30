// 063 (decision of 2026-09-29): explaining the recipes — on the Recipe card, for each setting, the meaning of the
// chosen value and the per-item cost budget; on the Settings › Recipes page, the full description. The budget
// calculation mirrors the service's `work.item_budget` (the test recipes are artificial).
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Recipe, type RecipeHelp } from "./api";
import { itemBudget, itemBudgetLines } from "./labels";
import { RecipeParamList, RecipesPanel } from "./views/RecipeInfo";

afterEach(() => vi.restoreAllMocks());

const INVOICE: Recipe = {
  id: "invoice-extraction", version: 5, title: "Számlák adatainak kinyerése", description: "Leírás.", steps: ["Beolvasás (szükség esetén OCR)"],
  requirements: ["Legalább egy PDF-irat a munkacsomagban"], result: "Iratonként mezőnkénti adat forrással, ellenőrzési eredménnyel és okonkénti teendőkkel.",
  manual_action: "A teendők rendezése, majd éles módban a futás jóváhagyása.",
  params: { arm: { allowed: ["auto", "S", "G"], default: "auto" }, jev_cache: { allowed: ["reuse", "live"], default: "reuse" } },
  max_item_usd: { S: { jev: "0.05" }, G: { jev: "0.05", openai: "0.10" }, auto: { jev: "0.05", openai: "0.10" } },
};
const EMAIL: Recipe = {
  ...INVOICE, id: "email-intent", title: "Levelek szándékának felismerése",
  params: { arm: { allowed: ["auto", "S", "G"], default: "auto" }, tasks: { allowed: ["off", "propose"], default: "off" } },
  max_item_usd: { "*": { jev: "0.05" } },
  max_item_usd_by_kind: { email: { "*": { jev: "0.05" } }, document: { S: { jev: "0.07", openai: "0.10" }, auto: { jev: "0.07", openai: "0.10" } } },
  param_item_usd: [{ param: "tasks", value: "propose", kind: "email", usd: { openai: "0.006" } }],
};
const HELP: RecipeHelp = {
  recipes: { "invoice-extraction": { when: "Ha a csomagban egyféle, ismert típusú irat van (például csak magyar számlák vagy csak villamosenergia-számlák). A típust te adod meg, a rendszer külön nem ismeri fel." } },
  params: {
    arm: { help: "Hogyan olvassa ki a rendszer az adatokat az iratból. Bármelyik út után kódos ellenőrzés jön (például az adószám ellenőrzőszáma, az összegek egyezése); ami bizonytalan, teendő lesz.",
      options: { S: "A kód kigyűjti a lehetséges értékeket (számlaszám-, dátum- és összegjelölteket), a JEV mezőnként választ közülük. Csak JEV-hívás, ezért olcsóbb; tételsorokat nem olvas. Egyes irattípusok csak a G utat ismerik." } },
    jev_cache: { help: "Mi történjen, ha ugyanazt a kérdést korábban már feltettük a JEV-nek.", options: {} },
  },
};

describe("063 a receptek magyarázata", () => {
  it("a tételkeret a szolgáltatás számítását követi: út szerint, tétel-fajtánként, a feladatjavaslat többletével", () => {
    expect(itemBudget(INVOICE, { arm: "S" })).toEqual({ jev: 0.05 });
    expect(itemBudget(INVOICE, { arm: "G" })).toEqual({ jev: 0.05, openai: 0.1 });
    expect(itemBudget(EMAIL, { arm: "auto", tasks: "off" }, "email")).toEqual({ jev: 0.05 });
    expect(itemBudget(EMAIL, { arm: "auto", tasks: "propose" }, "email")).toEqual({ jev: 0.05, openai: 0.006 });
    expect(itemBudget(EMAIL, { arm: "auto", tasks: "propose" }, "document")).toEqual({ jev: 0.07, openai: 0.1 });
    expect(itemBudgetLines(EMAIL, { arm: "auto", tasks: "off" })).toEqual(["levelenként: JEV legfeljebb 0,05 USD", "PDF-csatolmányonként: JEV legfeljebb 0,07 USD, OpenAI legfeljebb 0,10 USD"]);
  });

  it("a kártyán a választott érték jelentése látszik, érték-szöveg híján a beállításé, és a keret", () => {
    render(<RecipeParamList recipe={INVOICE} params={{ arm: "S", jev_cache: "live" }} help={HELP} />);
    expect(screen.getByText(/A kód kigyűjti a lehetséges értékeket/)).toBeTruthy();
    expect(screen.getByText(/Mi történjen, ha ugyanazt a kérdést/)).toBeTruthy(); // the test has no text for the „mindig élő” (always live) value
    expect(screen.getByText("tételenként: JEV legfeljebb 0,05 USD")).toBeTruthy();
  });

  it("a Receptek oldal a teljes leírást adja: mikor való, feltételek, lépések, eredmény, alapbeállítás, lehetőségenkénti keret", async () => {
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [INVOICE], help: HELP });
    render(<RecipesPanel />);
    expect(await screen.findByRole("region", { name: "Számlák adatainak kinyerése" })).toBeTruthy();
    expect(screen.getByText(/Ha a csomagban egyféle, ismert típusú irat van/)).toBeTruthy();
    expect(screen.getByText("Legalább egy PDF-irat a munkacsomagban")).toBeTruthy();
    expect(screen.getByText("Beolvasás (szükség esetén OCR)")).toBeTruthy();
    expect(screen.getAllByText("alapbeállítás").length).toBe(2); // the default of the path and of the JEV answers
    // the path affects the cost too, so the budget is shown for each option; for the JEV answers it is not
    expect(screen.getByText("Költségkeret: tételenként: JEV legfeljebb 0,05 USD")).toBeTruthy();
    expect(screen.getAllByText(/^Költségkeret: /).length).toBe(3);
  });
});
