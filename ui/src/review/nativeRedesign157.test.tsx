// 157 (redesign): the native view uses the shared button styles (no bare browser buttons), its saving is the solid
// action only while there is something to save, and the run's cost is set in the text face, not monospace.
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { setActor, type RunCostView, type RunView } from "../api";
import { setLanguage } from "../i18n";
import type { NativeItemResult } from "../native";
import { RunCost } from "../views/Runs";
import { NativeFactPanel } from "./NativeFactPanel";
import fixtures from "./native109.fixture.json";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => cleanup());

describe("the native view (157)", () => {
  it("draws every button with a shared style and keeps saving quiet while there is nothing to save", () => {
    const result = clone(fixtures.items.complete) as NativeItemResult;
    const { container } = render(<NativeFactPanel result={result} source={null} selected={null} readOnly={false}
      onChanged={() => {}} onCitation={() => {}} />);
    const buttons = [...container.querySelectorAll("button")];
    expect(buttons.length).toBeGreaterThan(0);
    expect(buttons.filter((b) => !b.className.trim())).toEqual([]);
    expect(container.querySelectorAll("button.primary")).toHaveLength(0);
  });
});

describe("the run's cost (157)", () => {
  it("sets the total in the text face with tabular figures, not monospace", () => {
    const costs = { total: { usd: "0.052676", calls: 120 }, providers: [] } as unknown as RunCostView;
    const budget = { scope: "run-1", committed_usd: "0", providers: {} } as unknown as RunView["budget"];
    const { container } = render(<RunCost costs={costs} budget={budget} budgetBlocked={false} />);
    expect(container.querySelector(".cost-total strong")?.classList.contains("mono")).toBe(false);
    expect(container.querySelector(".mono")).toBeNull();
  });
});
