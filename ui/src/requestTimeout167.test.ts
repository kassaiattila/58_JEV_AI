// 167 (review 160 U-14): a read that never answers gives up after a minute (a view's refresh used to stop for good
// behind it); a change is not cut off.
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError, READ_TIMEOUT_MS } from "./api";
import { setLanguage } from "./i18n";

beforeEach(async () => { await setLanguage("en"); vi.useFakeTimers(); });
afterEach(async () => { vi.useRealTimers(); vi.restoreAllMocks(); await setLanguage("hu"); });

/** A fetch that never answers, except by the abort of its signal. */
function hangingFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation((_url, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
  }));
}

it("a read gives up after a minute with its own message", async () => {
  hangingFetch();
  const pending = api.workpackage("wp-1").catch((e: unknown) => e);
  await vi.advanceTimersByTimeAsync(READ_TIMEOUT_MS + 1);
  const err = (await pending) as ApiError;
  expect(err).toBeInstanceOf(ApiError);
  expect(err.code).toBe("timeout");
  expect(err.message).toBe("The local service did not answer within a minute; the view will try again.");
});

it("a change has no time limit", async () => {
  const f = hangingFetch();
  let settled = false;
  void api.approve("run-1", "v1", 0).finally(() => { settled = true; }).catch(() => {});
  await vi.advanceTimersByTimeAsync(READ_TIMEOUT_MS * 3);
  expect(settled).toBe(false);
  expect((f.mock.calls[0][1] as RequestInit).signal).toBeUndefined();
});
