// 167 (review 160 U-8, U-9, 153 E): a budget rounded up to the cent keeps 0.07 (the float noise made it 0.08), a new
// estimate replaces a proposed budget but not a typed one, and a refused request names its fields, not "HTTP 422".
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { setLanguage } from "./i18n";
import { centsUp, mergeProposal } from "./views/workflows/labels";

beforeEach(async () => { await setLanguage("en"); });
afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

it.each([[0.07, "0.07"], ["0.071", "0.08"], ["0.447741", "0.45"], [0, "0.00"], ["1.10", "1.10"]])("rounds %s up to %s", (v, want) => {
  expect(centsUp(v)).toBe(want);
});

it("a new estimate replaces the proposed budget and keeps the typed one", () => {
  expect(mergeProposal({ jev: "0.10", openai: "0.50" }, { jev: "0.20", openai: "0.70" }, { openai: true }))
    .toEqual({ jev: "0.20", openai: "0.50" });
});

it("a refused request body names its fields", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: [
    { loc: ["body", "budget", "jev"], msg: "bad" }, { loc: ["body", "budget", "jev"], msg: "bad" }, { loc: ["body", "name"], msg: "x" },
  ] }), { status: 422 }));
  let err: ApiError | null = null;
  try {
    await api.workpackage("wp-1");
  } catch (e) {
    err = e as ApiError;
  }
  expect(err?.message).toBe("The service refused a value: jev, name");
});
