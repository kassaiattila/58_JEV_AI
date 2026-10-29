// 066 Á20: until now an unsaved field correction (working copy) lived only in memory, and was lost without a warning on
// reload. Now it is also kept in the tab's storage (it comes back after a reload), and with an unsaved correction the
// browser warns.
import { afterEach, describe, expect, it } from "vitest";
import { draftKey, getDraft, hydrateDrafts, resetDrafts, setField } from "./drafts";

afterEach(() => resetDrafts());

function leaving(): boolean {
  const e = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(e);
  return e.defaultPrevented;
}

describe("The working copy after a reload (066 Á20)", () => {
  it("it comes back from the tab's storage", () => {
    const key = draftKey("run-1", "it-1");
    setField(key, 3, "gross_total", "127000");
    const saved = sessionStorage.getItem("jav.drafts");
    resetDrafts();
    expect(getDraft(key)).toBeUndefined();
    sessionStorage.setItem("jav.drafts", saved ?? "");
    hydrateDrafts();
    expect(getDraft(key)).toEqual({ baseRevision: 3, values: { gross_total: "127000" }, sources: {} });
  });

  it("leaving the page warns with an unsaved correction, not in a clean state", () => {
    expect(leaving()).toBe(false);
    setField(draftKey("run-1", "it-1"), 1, "invoice_number", "X-1");
    expect(leaving()).toBe(true);
  });

  it("damaged stored data does not break the interface", () => {
    sessionStorage.setItem("jav.drafts", "{nem json");
    hydrateDrafts();
    expect(getDraft(draftKey("run-1", "it-1"))).toBeUndefined();
  });
});
