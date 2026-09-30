// 063: stabilitási átvizsgálás a felületen — a „nincs ilyen” (4xx) válasz után az automatikus frissítés nem kérdez
// újra másodpercenként (a nem létező futás oldala eddig a végtelenségig ismételte a kérést); a kézi frissítés működik.
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { useLoad } from "./hooks";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("063 automatikus frissítés", () => {
  it("4xx után nem ismétel, a kézi frissítés igen; átmeneti hibánál (5xx) tovább próbál", async () => {
    vi.useFakeTimers();
    const seconds = async (n: number) => { // lépésenként, hogy a React ne vonja össze a frissítéseket
      for (let i = 0; i < n; i++) await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    };
    const missing = vi.fn(() => Promise.reject(new ApiError(404, "not_found", "unknown id: run-nincs")));
    const hook = renderHook(() => useLoad("run:nincs", missing, 1000));
    await seconds(5);
    expect(missing).toHaveBeenCalledTimes(1);
    expect(hook.result.current.error?.status).toBe(404);
    await act(async () => { hook.result.current.reload(); await vi.advanceTimersByTimeAsync(10); });
    expect(missing).toHaveBeenCalledTimes(2);

    const flaky = vi.fn(() => Promise.reject(new ApiError(503, "unavailable", "átmeneti hiba")));
    renderHook(() => useLoad("run:atmeneti", flaky, 1000));
    await seconds(3);
    expect(flaky).toHaveBeenCalledTimes(4); // az első betöltés + másodpercenként egy
  });
});
