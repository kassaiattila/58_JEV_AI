// 123: a fact left out of a received answer is shown with its reason and names a to-do.
// Expectations avoid Hungarian letters for the language guard.
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { setActor } from "../api";
import { setLanguage } from "../i18n";
import { reasonText } from "../labels";
import type { NativeItemResult } from "../native";
import { NativeFactPanel } from "./NativeFactPanel";
import fixtures from "./native109.fixture.json";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
beforeEach(async () => { await setLanguage("hu"); setActor("Synthetic reviewer"); });

describe("left-out native facts (123)", () => {
  it("names the to-do with the number of left-out facts", () => {
    expect(reasonText("native:discarded_facts:2")).toMatch(/^2 adatjavaslat hib.s szerkezet. volt, ez.rt kimaradt/);
  });

  it("lists each left-out fact with its translated reason", () => {
    const result = clone(fixtures.items.complete) as NativeItemResult;
    result.interpretation = { ...result.interpretation!, discarded_facts: [
      { entity: "declaration", property: "signature place", state: "missing", reason: "Missing facts cannot invent a value" }] };
    render(<NativeFactPanel result={result} source={null} selected={null} readOnly={false}
      onChanged={() => {}} onCitation={() => {}} />);
    const line = screen.getByText(/Kimaradt adatjavaslat/);
    expect(line.textContent).toContain("declaration");
    expect(line.textContent).toContain("signature place");
    expect(line.textContent).toMatch(/hi.nyz.nak jel.lte/);
  });

  it("shows nothing extra for results saved before 123", () => {
    const result = clone(fixtures.items.complete) as NativeItemResult;
    render(<NativeFactPanel result={result} source={null} selected={null} readOnly={false}
      onChanged={() => {}} onCitation={() => {}} />);
    expect(screen.queryByText(/Kimaradt adatjavaslat/)).toBeNull();
  });
});
