// 265 (code review UI-15): after a confirmation or after closing the side panel, focus goes back to the button that
// opened it; it was lost with the card's or the panel's buttons, and a keyboard user had to start from the page's top.
// Invented content, no service.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setLanguage } from "../i18n";
import { ConfirmButton } from "./ConfirmButton";
import { SidePanel } from "./SidePanel";

beforeEach(async () => { await setLanguage("en"); localStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("265 focus comes back", () => {
  it("to the button after its confirmation", async () => {
    const done = vi.fn();
    render(<ConfirmButton onConfirm={done} question="Stop the invented run?">Stop</ConfirmButton>);
    const button = screen.getByRole("button", { name: "Stop" });
    fireEvent.click(button);
    fireEvent.click(screen.getAllByRole("button", { name: "Stop" })[1]);
    expect(done).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(document.activeElement).toBe(button));
  });

  it("to the panel's button after the panel is closed, hidden or pinned", () => {
    render(<SidePanel id="focus" label="Contents"><p>the tree</p></SidePanel>);
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    const reveal = screen.getByRole("button", { name: "Contents" });
    expect(document.activeElement).toBe(reveal);
    fireEvent.click(reveal);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.activeElement).toBe(reveal);
    fireEvent.click(reveal);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(document.activeElement).toBe(reveal);
    fireEvent.click(reveal);
    fireEvent.click(screen.getByRole("button", { name: "Pin" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Hide" }));
  });
});
