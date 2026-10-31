// 157 (redesign): Settings follow the design system. The density switch is gone (one density for everyone, as the
// design brief decided); a save button is the view's solid action only while there is something to save. The local
// service is replaced by spies; synthetic paths only.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor } from "../../api";
import { applyAppearance } from "../../appearance";
import { setLanguage } from "../../i18n";
import { AppearancePanel } from "./AppearancePanel";
import { FoldersPanel } from "./FoldersPanel";
import { UsersPanel } from "./UsersPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); delete document.documentElement.dataset.density; });

describe("appearance (157)", () => {
  it("offers the theme, with no density switch (264: and the interface language beside it)", () => {
    render(<AppearancePanel />);
    expect(screen.getAllByRole("radio").map((r) => (r as HTMLInputElement).name)).toEqual(["theme", "theme", "theme",
      "language", "language"]);
    expect(screen.queryByText("Density")).toBeNull();
  });

  it("ignores a density remembered from before", () => {
    localStorage.setItem("jav.appearance", JSON.stringify({ theme: "dark", density: "compact" }));
    applyAppearance();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.density).toBeUndefined();
    localStorage.removeItem("jav.appearance");
  });
});

describe("work folders (157)", () => {
  it("makes a save button solid only while there is something to save", async () => {
    vi.spyOn(api, "folders").mockResolvedValue({ folders: [], roots: [] });
    vi.spyOn(api, "outputFolder").mockResolvedValue({ path: "D:\\Synthetic" });
    render(<FoldersPanel />);
    const output = await screen.findByLabelText("Full folder path");
    expect(document.querySelectorAll("button.primary")).toHaveLength(0);
    fireEvent.change(output, { target: { value: "D:\\Synthetic\\new" } });
    const solid = [...document.querySelectorAll("button.primary")];
    expect(solid).toHaveLength(1);
    expect(solid[0].closest("fieldset")?.getAttribute("aria-label")).toBe("Output folder");
  });
});

describe("users (157)", () => {
  it("makes the add button solid only once a name is typed", async () => {
    vi.spyOn(api, "users").mockResolvedValue({ users: ["Synthetic reviewer"] });
    render(<UsersPanel />);
    const add = await screen.findByRole("button", { name: "Add" });
    expect(add.classList.contains("primary")).toBe(false);
    fireEvent.change(screen.getByLabelText("New name"), { target: { value: "Second reviewer" } });
    expect(add.classList.contains("primary")).toBe(true);
  });
});
