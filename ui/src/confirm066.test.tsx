// 066 Á36 (decision of 2026-09-29): releasing and stopping ask for a confirmation. 263 (plan E, F1; the owner's
// decision of 2026-10-31: a confirmation card everywhere): the button opens a card that says what happens, with
// "Cancel" and the action on the right; only the card's action carries it out.
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmButton } from "./components/ConfirmButton";
import { confirmAction } from "./confirm.testutil";

describe("Confirmation (066 Á36, 263 F1)", () => {
  it("the button opens a card that says what happens; its action carries it out", async () => {
    const run = vi.fn();
    const user = userEvent.setup();
    render(<ConfirmButton onConfirm={run} question="A köteg 4 tétele kiadódik.">Jóváhagyás és kiadás</ConfirmButton>);
    await user.click(screen.getByRole("button", { name: "Jóváhagyás és kiadás" }));
    expect(run).not.toHaveBeenCalled();
    const card = screen.getByRole("dialog", { name: "Megerősítés" });
    expect(card.textContent).toContain("A köteg 4 tétele kiadódik.");
    // "Cancel" first, then the action, the last on the right
    expect([...card.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Mégse", "Jóváhagyás és kiadás"]);
    await user.click(confirmAction());
    expect(run).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Cancel and Esc close the card without acting; a removal's action is the danger one", async () => {
    const run = vi.fn();
    const user = userEvent.setup();
    render(<ConfirmButton onConfirm={run} danger>Törlés</ConfirmButton>);
    await user.click(screen.getByRole("button", { name: "Törlés" }));
    expect(confirmAction().className).toBe("danger");
    await user.click(screen.getByRole("button", { name: "Mégse" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Törlés" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(run).not.toHaveBeenCalled();
  });
});
