import { act, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import catalogue from "../../configs/recipes.json";
import help from "../../configs/recipe_help.json";
import { api, type Recipe, type RecipeHelp } from "./api";
import { setLanguage } from "./i18n";
import { RecipeParamList, RecipesPanel } from "./views/RecipeInfo";

afterEach(async () => { vi.restoreAllMocks(); await act(() => setLanguage("hu")); });

it("distinguishes active recipes with visible names and independent recipe versions", async () => {
  vi.spyOn(api, "recipes").mockResolvedValue({
    recipes: catalogue.recipes.filter((recipe) => recipe.status === "active") as unknown as Recipe[],
    help: help as RecipeHelp,
  });
  render(<RecipesPanel />);
  expect(await screen.findByRole("heading", { name: "PDF-ek \u00e9s levelek feldolgoz\u00e1sa" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Dokumentumok feldolgoz\u00e1sa — PDF, Word, Excel, TXT, CSV" })).toBeTruthy();
  expect(screen.getAllByText("Receptverzi\u00f3: 2")).toHaveLength(2);
});

it("keeps email explanations out of the document-only recipe and explains its native path", async () => {
  vi.spyOn(api, "recipes").mockResolvedValue({
    recipes: catalogue.recipes.filter((recipe) => recipe.status === "active") as unknown as Recipe[],
    help: help as RecipeHelp,
  });
  render(<RecipesPanel />);
  const native = within(await screen.findByRole("region", {
    name: "Dokumentumok feldolgoz\u00e1sa — PDF, Word, Excel, TXT, CSV",
  }));
  expect(native.queryByText(/^(Lev\u00e9l|Levelek)$/, { selector: "dt" })).toBeNull();
  expect(native.getByText("Word, Excel, TXT \u00e9s CSV", { selector: "dt" })).toBeTruthy();
  expect(native.getByText(/PDF-en a felismert t\u00edpus aj\u00e1nlott \u00fatja fut/)).toBeTruthy();
  expect(native.queryByText(/A JEV ismeri fel az irat t\u00edpus\u00e1t \u00e9s a lev\u00e9l sz\u00e1nd\u00e9k\u00e1t/)).toBeNull();
});

it("uses the native recipe explanation on the package card and preserves it when changing language", async () => {
  const recipe = catalogue.recipes.find((entry) => entry.id === "multi-format-processing") as unknown as Recipe;
  render(<RecipeParamList recipe={recipe} params={{ jev: "off" }} help={help as RecipeHelp} kinds={["document"]} />);
  expect(screen.getByText(/A GPT nyeri ki az adatokat, JEV-h\u00edv\u00e1s n\u00e9lk\u00fcl/)).toBeTruthy();
  expect(screen.queryByText(/A levelek sz\u00e1nd\u00e9k\u00e1t is a GPT ismeri fel/)).toBeNull();
  await act(() => setLanguage("en"));
  expect(screen.getByText(/GPT extracts values without JEV calls/)).toBeTruthy();
  expect(screen.queryByText(/A GPT nyeri ki az adatokat/)).toBeNull();
});
