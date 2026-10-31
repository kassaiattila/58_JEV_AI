// 265 (code review UI-06): the run a review shows is in the address. It was kept only in the page, so a reload or a
// link showed the latest run, and an item of the chosen run then read "the item is not part of the run".
// Artificial identifiers, no service.
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseRoute, routeHash } from "./route";
import { itemChanged } from "./views/ReviewWorkspace";

afterEach(() => { window.location.hash = ""; });

describe("265 the review's run in the address", () => {
  it("goes there and back with the item", () => {
    const hash = `#/workpackages/wp-000000000009/review/${"b".repeat(64)}?run=run-invented-1`;
    const r = parseRoute(hash);
    expect(r).toMatchObject({ view: "workpackages", stage: "review", itemId: "b".repeat(64), runId: "run-invented-1" });
    expect(routeHash(r)).toBe(hash);
  });

  it("stays when the queue's item is put into the address after a change", () => {
    itemChanged("wp-1", true, "c".repeat(64), vi.fn(), undefined, "run-invented-2");
    expect(window.location.hash).toBe(`#/workpackages/wp-1/review/${"c".repeat(64)}?run=run-invented-2`);
  });
});
