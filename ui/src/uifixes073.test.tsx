// 073 (Q-felület-maradék): task-proposal review reasons in words, friendly Outlook errors in the download log, the
// English "Recipes" menu label, and two-click confirmation for the remaining one-click deletions.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import english from "./i18n/en";
import { setLanguage } from "./i18n";
import { reasonText } from "./labels";
import { pullErrorText, pullSummary } from "./views/Mailbox";
import { SETTINGS_SECTIONS } from "./views/Settings";
import { UsersPanel } from "./views/settings/UsersPanel";

afterEach(async () => {
  vi.restoreAllMocks();
  await setLanguage("hu");
});

describe("task proposal review reasons (073)", () => {
  it("are shown as a sentence, not as the raw code", () => {
    expect(reasonText("tasks:proposed:3")).toBe("3 feladatjavaslat vár döntésre");
    expect(reasonText("tasks:failed:TimeoutError")).toBe("A feladatjavaslat nem sikerült (TimeoutError)");
  });

  it("have an English translation", async () => {
    await setLanguage("en");
    expect(reasonText("tasks:proposed:2")).toBe("2 task proposal(s) awaiting a decision");
    expect(reasonText("tasks:failed:ValueError")).toBe("Task proposal failed (ValueError)");
  });
});

describe("download errors (073)", () => {
  it("a known Outlook script error is shown in the UI language in the log and the schedule", () => {
    const raw = "Outlook must already be running in the current interactive session.";
    expect(pullErrorText(raw)).toBe("Az Outlook nem fut ezen a gépen. Indítsd el, és próbáld újra.");
    expect(pullSummary({ status: "error", result: { error: raw } })).toBe("Az Outlook nem fut ezen a gépen. Indítsd el, és próbáld újra.");
  });

  it("any other error is shown unchanged, without the Outlook prefix", () => {
    const worker = "A letöltés megszakadt (JobCancelled); a megérkezett levelekből csomag készült.";
    expect(pullErrorText(worker)).toBe(worker);
    expect(pullSummary({ status: "error", result: {} })).toBe("Hiba");
  });
});

describe("settings menu translations (073)", () => {
  it("every section label and hint has an English translation", () => {
    const missing = SETTINGS_SECTIONS.flatMap((s) => [s.label, s.hint]).filter((k) => !(k in english));
    expect(missing).toEqual([]);
    expect(english["Receptek"]).toBe("Recipes");
  });
});

describe("one-click deletions ask for confirmation (073)", () => {
  it("removing a user needs a second click", async () => {
    vi.spyOn(api, "users").mockResolvedValue({ users: ["Minta Anna", "Teszt Elek"] });
    const save = vi.spyOn(api, "saveUsers").mockImplementation(async (users) => ({ users }));
    const user = userEvent.setup();
    render(<UsersPanel />);
    await screen.findByText("Minta Anna");
    await user.click(screen.getByRole("button", { name: "Minta Anna törlése a listából" }));
    expect(save).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Biztosan? Kattints újra" }));
    expect(save).toHaveBeenLastCalledWith(["Teszt Elek"]);
  });
});
