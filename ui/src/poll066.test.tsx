// 066 Á36: az automatikus frissítés időzítője eddig akkor is új kérést indított, ha az előző még nem tért vissza (lassú
// szolgáltatásnál a kérések torlódtak), és rejtett lapon is kérdezett. Most függő kérés alatt és rejtett lapon kimarad.
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useLoad } from "./hooks";

afterEach(() => {
  vi.useRealTimers();
  Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
});

function Poller({ fn }: { fn: () => Promise<number> }) {
  useLoad("k", fn, 1000);
  return null;
}

describe("Automatikus frissítés (066 Á36)", () => {
  it("függő kérés alatt nem indít újat", async () => {
    vi.useFakeTimers();
    const fn = vi.fn(() => new Promise<number>(() => {})); // sosem tér vissza
    render(<Poller fn={fn} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(5500); });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("rejtett lapon nem kérdez", async () => {
    vi.useFakeTimers();
    const fn = vi.fn(async () => 1);
    render(<Poller fn={fn} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    const before = fn.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(5500); });
    expect(fn.mock.calls.length).toBe(before);
  });
});
