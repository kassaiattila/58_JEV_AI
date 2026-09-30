// 066 Á23: until now an error from the „Rendezve” (Resolved) button was lost silently, and the button could be pressed
// again while the request was pending.
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type Reason } from "../api";
import { useResolve } from "./useResolve";

afterEach(() => vi.restoreAllMocks());

const R = { id: 7, reason: "pick:low_conf:gross_total:0.4" } as unknown as Reason;

function Probe({ onDone }: { onDone: () => void }) {
  const { resolve, pending, error } = useResolve(onDone);
  return (
    <div>
      <button type="button" disabled={pending !== null} onClick={() => void resolve(R)}>Rendezve</button>
      {error ? <p role="alert">{error}</p> : null}
    </div>
  );
}

describe("Teendő rendezése (066 Á23)", () => {
  it("a hiba látszik, és a lista akkor is frissül", async () => {
    vi.spyOn(api, "resolveReason").mockRejectedValue(new ApiError(409, "conflict", "already resolved"));
    const onDone = vi.fn();
    render(<Probe onDone={onDone} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Rendezve" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Nem sikerült rendezni: already resolved");
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("két gyors kattintás egy kérést küld", async () => {
    let finish: (v: { status: string }) => void = () => {};
    const spy = vi.spyOn(api, "resolveReason").mockImplementation(() => new Promise((res) => { finish = res; }));
    render(<Probe onDone={() => {}} />);
    const btn = screen.getByRole("button", { name: "Rendezve" });
    await act(async () => { btn.click(); btn.click(); });
    expect(spy).toHaveBeenCalledTimes(1);
    await act(async () => finish({ status: "resolved" }));
  });
});
