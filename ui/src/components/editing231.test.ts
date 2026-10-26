// 231 (stage D0, D0-g; the reassessment of 2026-10-26, F15, P12): the shared save behaviour's logic. My changes since
// the version I started from are compared with the version saved now field by field, marked where they changed it too;
// keeping mine applies only my changes over theirs. Unsaved work lives in the page's memory only, and the browser warns
// before the page is left with any. Synthetic data.
import { describe, expect, it } from "vitest";
import { compare, hasWork, keepWork, merge, resetWork, saveState, workOf } from "./editing";

type Row = { id: string | null; quantity: string; note: string | null };
const BASE: { version: number; header: { customer: string; note: string | null }; lines: Row[] } = {
  version: 1, header: { customer: "Invented Ltd", note: null },
  lines: [{ id: "x", quantity: "1", note: null }, { id: "y", quantity: "2", note: null }] };

describe("the save line's state", () => {
  it("names a failure first, then a save under way, a change, a save", () => {
    expect(saveState({ saving: true, failed: "conflict", changed: true, savedAt: null })).toBe("conflict");
    expect(saveState({ saving: false, failed: "unknown", changed: false, savedAt: "t" })).toBe("unknown");
    expect(saveState({ saving: true, failed: null, changed: true, savedAt: null })).toBe("saving");
    expect(saveState({ saving: false, failed: null, changed: true, savedAt: "t" })).toBe("changed");
    expect(saveState({ saving: false, failed: null, changed: false, savedAt: "t" })).toBe("saved");
    expect(saveState({ saving: false, failed: null, changed: false, savedAt: null })).toBe("clean");
  });
});

describe("my changes beside theirs", () => {
  const mine = { ...BASE, header: { ...BASE.header, customer: "Invented Buyer Ltd" },
    lines: [{ id: "x", quantity: "3", note: null }, { id: null, quantity: "9", note: "new" }] };  // y removed, one added
  const theirs = { ...BASE, version: 2, header: { ...BASE.header, note: "their note" },
    lines: [{ id: "x", quantity: "4", note: null }, { id: "y", quantity: "2", note: null }, { id: "z", quantity: "5", note: null }] };

  it("lists each of my changes with the value saved now, marked where they changed it too", () => {
    const out = compare(BASE, mine, theirs).map((c) => [c.path.join("/"), c.mine, c.theirs, c.both]);
    expect(out).toEqual([
      ["header/customer", "Invented Buyer Ltd", "Invented Ltd", false],
      ["lines/#x/quantity", "3", "4", true],
      ["lines/#y", undefined, true, false],
      ["lines/+1", { id: null, quantity: "9", note: "new" }, undefined, false],
    ]);
  });

  it("keeps theirs where I changed nothing, and applies mine over it", () => {
    expect(merge(theirs, BASE, mine)).toEqual({ version: 2, header: { customer: "Invented Buyer Ltd", note: "their note" },
      lines: [{ id: "x", quantity: "3", note: null }, { id: "z", quantity: "5", note: null }, { id: null, quantity: "9", note: "new" }] });
  });

  it("marks a change to a row they removed, and leaves it out", () => {
    const gone = { ...theirs, lines: [{ id: "y", quantity: "2", note: null }] };
    const change = compare(BASE, { ...BASE, lines: [{ id: "x", quantity: "7", note: null }, BASE.lines[1]] }, gone);
    expect(change.map((c) => [c.path.join("/"), c.theirs, c.both])).toEqual([["lines/#x/quantity", undefined, true]]);
    expect(merge(gone, BASE, { ...BASE, lines: [{ id: "x", quantity: "7", note: null }, BASE.lines[1]] }).lines).toEqual(gone.lines);
  });

  it("finds nothing to keep when the version saved now holds my changes already (an added row with its new id)", () => {
    const already = { ...structuredClone(mine), lines: [{ id: "x", quantity: "3", note: null }, { id: "w", quantity: "9", note: "new" }] };
    expect(JSON.stringify(merge(already, BASE, mine))).toBe(JSON.stringify(already));
    expect(compare(BASE, mine, already).find((c) => c.path.join("/") === "lines/+1")?.theirs).toEqual({ id: "w", quantity: "9", note: "new" });
  });

  it("removes every row I removed without wiping a row they added", () => {
    const none = { ...BASE, lines: [] as typeof BASE.lines };
    expect(merge(theirs, BASE, none).lines).toEqual([{ id: "z", quantity: "5", note: null }]);
  });
});

describe("the page's memory of unsaved work", () => {
  const leaving = () => { const e = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented; };

  it("keeps it by what it edits, never in the browser's storage, and warns before the page is left", () => {
    resetWork();
    expect(leaving()).toBe(false);
    keepWork("quote:wp-1:compose", { typed: "3" });
    expect(hasWork("quote:wp-1:compose") && hasWork() && !hasWork("quote:wp-2:compose")).toBe(true);
    expect(workOf("quote:wp-1:compose")).toEqual({ typed: "3" });
    expect(sessionStorage.length + localStorage.length).toBe(0);
    expect(leaving()).toBe(true);
    keepWork("quote:wp-1:compose", null);
    expect(leaving()).toBe(false);
  });
});
