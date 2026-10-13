// 153 (review B7): the automatic refresh of a table or a view waits while its request is pending. A table whose query
// was slower than its refresh never filled (every answer was superseded by the next request) and the requests piled up;
// a view refreshed by hand during a slow request stopped refreshing, because the superseded request's end cleared the
// pending mark. Artificial timing, no service.
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsPage } from "./api";
import { useDataset, useLoad } from "./hooks";

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

const slow = <T,>(value: () => T, ms: number) => () => new Promise<T>((resolve) => { setTimeout(() => resolve(value()), ms); });

/** Lets time pass in small steps, so each timer's state change renders before the next one. */
async function pass(ms: number) {
  for (let t = 0; t < ms; t += 500) await act(async () => { await vi.advanceTimersByTimeAsync(500); });
}

describe("153 a refresh slower than its interval", () => {
  it("a table still fills and asks one request at a time", async () => {
    vi.useFakeTimers();
    let n = 0;
    const query = vi.spyOn(api, "datasetQuery").mockImplementation(slow(() => ({ rows: [], total: ++n }) as unknown as DsPage, 3500));
    const { result } = renderHook(() => useDataset("workpackages", {}, {}, 3000));
    await pass(30_000);
    expect(result.current.data?.total).toBeGreaterThanOrEqual(3); // newer answers keep arriving
    expect(query.mock.calls.length).toBe(n + 1); // every request but the pending one was answered and shown
  });

  it("a superseded request ending does not let the refresh start while the newest one is pending", async () => {
    vi.useFakeTimers();
    const answers: ((v: number) => void)[] = [];
    const fn = vi.fn(() => new Promise<number>((resolve) => { answers.push(resolve); }));
    const { result } = renderHook(() => useLoad("run-1", fn, 3000));
    await act(async () => { answers[0](1); });
    await pass(3_000); // the refresh asks again: the second request is pending
    expect(fn).toHaveBeenCalledTimes(2);
    act(() => result.current.reload()); // a manual reload supersedes it
    expect(fn).toHaveBeenCalledTimes(3);
    await act(async () => { answers[1](2); }); // the superseded request ends
    await pass(6_000);
    expect(fn).toHaveBeenCalledTimes(3); // before: its end cleared the mark and every refresh superseded the newest
    await act(async () => { answers[2](3); });
    expect(result.current.data).toBe(3);
  });
});
