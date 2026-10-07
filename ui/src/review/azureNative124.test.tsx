// 124: a scan read from its Azure recognition says so, and its recognition to-dos have readable labels.
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

describe("Azure recognition in native results (124)", () => {
  it("labels the recognition to-dos", () => {
    expect(reasonText("native:recognition:low_confidence:0.45")).toMatch(/^Gyenge Azure-felismer.s \(0,45\)$/);
    expect(reasonText("native:recognition:low_conf_words:1.00")).toMatch(/^Sok bizonytalan sz. az Azure-felismer.sben/);
    expect(reasonText("native:recognition:azure_blocked:budget_exceeded")).toMatch(/futas kerete|fut.s kerete/);
    expect(reasonText("native:recognition:azure_blocked:unavailable")).toMatch(/nem siker.lt; helyi felismer.s k.sz.lt$/);
  });

  it("says which pages Azure read and how sure it was", () => {
    const result = clone(fixtures.items.complete) as NativeItemResult;
    result.reading.results[0].recognition = { provider: "azure_di", model: "prebuilt-read", pages: [1, 2], words: 40,
      mean_conf: 0.97, low_conf_ratio: 0.02 };
    render(<NativeFactPanel result={result} source={null} selected={null} readOnly={false}
      onChanged={() => {}} onCitation={() => {}} />);
    const line = screen.getByText(/Azure olvasta/);
    expect(line.textContent).toContain("1, 2");
    expect(line.textContent).toContain("0,97");
  });

  it("shows nothing extra for a reading without an Azure recognition", () => {
    const result = clone(fixtures.items.complete) as NativeItemResult;
    render(<NativeFactPanel result={result} source={null} selected={null} readOnly={false}
      onChanged={() => {}} onCitation={() => {}} />);
    expect(screen.queryByText(/Azure olvasta/)).toBeNull();
  });
});
