// 195 (plan G-tidy R6): the shared action behind a page's buttons - busy while it runs, one at a time, then the page's
// follow-up and a notice, or the error in the page's own words.
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { errorText, useAction } from "./hooks";

describe("the shared action (195)", () => {
  it("is busy while it runs, starts no second one, then follows up and gives its notice", async () => {
    const { result } = renderHook(() => useAction());
    let finish: (v: number) => void = () => {};
    const seen: number[] = [];
    let first: Promise<boolean> = Promise.resolve(false);
    act(() => { first = result.current.run(() => new Promise<number>((r) => { finish = r; }), { then: (v) => seen.push(v), done: "Saved." }); });
    await waitFor(() => expect(result.current.busy).toBe(true));
    let second = true;
    await act(async () => { second = await result.current.run(async () => 2); });
    expect(second).toBe(false);
    await act(async () => { finish(1); expect(await first).toBe(true); });
    expect(seen).toEqual([1]);
    expect(result.current).toMatchObject({ busy: false, notice: "Saved.", error: null });
  });

  it("shows a failure in the page's words, or the service's own message", async () => {
    const { result } = renderHook(() => useAction());
    const conflict = new ApiError(409, "revision_conflict", "changed");
    await act(async () => { await result.current.run(() => Promise.reject(conflict), { failed: (e) => `own: ${errorText(e)}` }); });
    expect(result.current.error).toBe("own: changed");
    await act(async () => { await result.current.run(() => Promise.reject(new ApiError(422, "invalid", "bad value"))); });
    expect(result.current).toMatchObject({ error: "bad value", notice: null, busy: false });
  });
});
