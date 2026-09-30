// 076: paid calls with an uncertain outcome on the System page — the list, the cost check, and settling one sends the
// cost (or none) and the note to the service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type UncertainCall } from "./api";
import { UncertainCallsPanel, parseCost } from "./views/settings/UncertainCallsPanel";

afterEach(() => vi.restoreAllMocks());

const CALL: UncertainCall = {
  id: 7, run_id: "run-x", step_id: "s1", attempt: 1, provider: "openai", model_requested: "m", budget_scope: "run-x",
  max_cost_usd: "0.20", created_at: "2026-09-30T10:00:00+00:00", status: "uncertain",
};

describe("076 uncertain calls on the System page", () => {
  it("reads a typed cost", () => {
    expect(parseCost("")).toEqual({ ok: true, value: null });
    expect(parseCost(" 0,012 ")).toEqual({ ok: true, value: "0.012" });
    expect(parseCost("-1").ok).toBe(false);
    expect(parseCost("abc").ok).toBe(false);
  });

  it("says when there is nothing to settle", async () => {
    vi.spyOn(api, "uncertainCalls").mockResolvedValue({ calls: [] });
    render(<UncertainCallsPanel />);
    expect((await screen.findByRole("status")).textContent).toMatch(/Nincs lezáratlan/);
  });

  it("settles a call with the cost and the note after the second click", async () => {
    vi.spyOn(api, "uncertainCalls").mockResolvedValue({ calls: [CALL] });
    const resolve = vi.spyOn(api, "resolveUncertainCall").mockResolvedValue({ ok: true });
    render(<UncertainCallsPanel />);
    expect((await screen.findByRole("status")).textContent).toMatch(/1 fizetős hívásnál/);
    fireEvent.change(screen.getByLabelText(/Tényleges költség/), { target: { value: "0,07" } });
    fireEvent.change(screen.getByLabelText(/Megjegyzés/), { target: { value: "a konzolon ellenőrizve" } });
    const button = screen.getByRole("button", { name: "Lezárás" });
    fireEvent.click(button);
    expect(resolve).not.toHaveBeenCalled();  // the first click only arms the confirmation
    fireEvent.click(screen.getByRole("button", { name: "Biztosan? Kattints újra" }));
    await waitFor(() => expect(resolve).toHaveBeenCalledWith(7, { cost_usd: "0.07", note: "a konzolon ellenőrizve" }));
  });
});
