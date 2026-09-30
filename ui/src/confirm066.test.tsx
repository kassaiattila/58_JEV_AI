// 066 Á36 (decision of 2026-09-29): releasing and stopping are carried out on the second click.
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CONFIRM_WINDOW_MS, ConfirmButton } from "./components/ConfirmButton";

afterEach(() => vi.useRealTimers());

describe("Megerősítés (066 Á36)", () => {
  it("az első kattintás csak élesít, a második végrehajt", async () => {
    const run = vi.fn();
    const user = userEvent.setup();
    render(<ConfirmButton onConfirm={run}>Jóváhagyás és kiadás</ConfirmButton>);
    await user.click(screen.getByRole("button", { name: "Jóváhagyás és kiadás" }));
    expect(run).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Biztosan? Kattints újra" }));
    expect(run).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Jóváhagyás és kiadás" })).toBeTruthy();
  });

  it("néhány másodperc után visszaáll, és újra két kattintás kell", async () => {
    vi.useFakeTimers();
    const run = vi.fn();
    render(<ConfirmButton onConfirm={run}>Leállítás</ConfirmButton>);
    act(() => screen.getByRole("button").click());
    expect(screen.getByRole("button").textContent).toBe("Biztosan? Kattints újra");
    act(() => { vi.advanceTimersByTime(CONFIRM_WINDOW_MS + 10); });
    expect(screen.getByRole("button").textContent).toBe("Leállítás");
    act(() => screen.getByRole("button").click());
    expect(run).not.toHaveBeenCalled();
  });
});
