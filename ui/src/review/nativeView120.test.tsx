// 120: the native review reads in everyday words; raw machine codes stay in the technical details.
// Hungarian expectations use explicit codepoints for the language guard.
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { setActor } from "../api";
import { setLanguage } from "../i18n";
import { reasonText } from "../labels";
import type { NativeItemResult } from "../native";
import { NativeFactPanel } from "./NativeFactPanel";
import { issueSummary, outcomeReasonText } from "./nativeLabels";
import fixtures from "./native109.fixture.json";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
beforeEach(async () => { await setLanguage("hu"); setActor("Synthetic reviewer"); });

describe("native review in everyday words (120)", () => {
  it("groups reading issues by kind with a count", () => {
    const issues = [{ code: "unread_content" }, { code: "unread_content" }, { code: "needs_ocr" }];
    expect(issueSummary(issues)).toEqual([
      "Egyes tartalmak csak az eredetiben maradtak meg, p\u00e9ld\u00e1ul megjelen\u00edt\u00e9si form\u00e1tum vagy be\u00e1gyazott objektum (2 helyen)",
      "K\u00e9pek vagy szkennelt r\u00e9szek nem lettek sz\u00f6vegk\u00e9nt kiolvasva",
    ]);
  });

  it("translates outcome reasons and keeps an error class as it is", () => {
    expect(outcomeReasonText("Interpretation stopped: MissingAPIKeyError")).toBe("Az \u00e9rtelmez\u00e9s le\u00e1llt (MissingAPIKeyError)");
    expect(outcomeReasonText("The configured provider budget is exhausted")).toBe("A fut\u00e1s szolg\u00e1ltat\u00f3i kerete elfogyott");
  });

  it("names native to-dos in sentences, counting facts from one", () => {
    expect(reasonText("native:fact:2:unsupported:0.15")).toBe("A JEV nem t\u00e1masztja al\u00e1 a(z) 3. adatjavaslatot (0,15)");
    expect(reasonText("native:fact:0:requires_review")).toBe("A(z) 1. adatjavaslathoz figyelmeztet\u00e9s tartozik; ellen\u0151rizd");
    expect(reasonText("native:reading:partial")).toBe("Az irat nem teljesen olvashat\u00f3 (r\u00e9szleges); n\u00e9zd meg a forr\u00e1st \u00e9s a hi\u00e1nyokat");
    expect(reasonText("native:no_facts")).toBe("Az iratb\u00f3l nem keletkezett adatjavaslat");
  });

  it("shows one grouped issue line and a translated warning, raw codes only in the details", () => {
    const result = clone(fixtures.items.partial) as NativeItemResult;
    const issue = result.reading.results[0].issues[0];
    result.reading.results[0].issues = [issue, { ...issue, element_id: "e9" }];
    result.native_facts = clone((fixtures.items.complete as NativeItemResult).native_facts);
    result.native_facts[0].reasons = ["Value looks like an unfilled template placeholder, not a stated fact"];
    const { container } = render(<NativeFactPanel result={result} source={null} selected={null} readOnly={false}
      onChanged={() => {}} onCitation={() => {}} />);
    const summary = container.querySelector(".native-summary")!;
    const visible = [...summary.children].filter((e) => e.tagName === "P").map((e) => e.textContent ?? "");
    expect(visible.filter((text) => text.includes("(2 helyen)"))).toHaveLength(1);
    expect(visible.some((text) => text.includes(issue.code))).toBe(false);
    expect(summary.querySelector("details")?.textContent).toContain(issue.code);
    expect(screen.getByText("Az \u00e9rt\u00e9k kit\u00f6ltetlen sablonmez\u0151nek t\u0171nik, nem k\u00f6z\u00f6lt adatnak")).toBeTruthy();
  });
});
