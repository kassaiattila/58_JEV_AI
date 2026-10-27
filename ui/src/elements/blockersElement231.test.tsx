// 231 (stage D, D-f9): what holds a case, on its Overview: each step with what holds it and the view where it is
// resolved as a link; nothing holding it, or a closed case, is one quiet line. Invented data.
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { BlockersData, CaseView } from "../api";
import { setLanguage } from "../i18n";
import { blockersStatus } from "./caseStatus";
import { elementOf } from "./registry";

beforeEach(async () => { await setLanguage("en"); });

const CASE = "wp-0000000d0f90";

function show(data: BlockersData) {
  const step = (title: string, uses: string): CaseView["steps"][string] => ({ title, uses, start: "auto", state: "running", phase: null,
    waiting_for: null, awaiting_start: false, note: null, result: null, actions: [] });
  const page: CaseView = {
    case: { id: CASE, pack: "insurance_offer", version: "1.6.0", title: "Insurance quote", name: "Minta Kft.", status: "open" },
    steps: { rate: step("Premium", "rating@1"), letter: step("Covering letter", "letter@1") },
    tabs: [{ id: "overview", label: "Overview", elements: [{ type: "blockers", step: null, data }] },
           { id: "decision", label: "Decision and release", elements: [] }], next: null,
  };
  render(<>{elementOf("blockers")!.render({ caseId: CASE, element: page.tabs[0].elements[0], page, onChanged: () => {} })}</>);
}

describe("what holds a case", () => {
  it("names each step with what holds it and links the view where it is resolved", async () => {
    const data: BlockersData = { status: "open", items: [
      { step: "rate", kind: "stopped", note: "blocked: the tariff has no rate", waiting_for: null, tab: null },
      { step: "letter", kind: "person", note: null, waiting_for: "letter", tab: "decision" }] };
    show(data);
    expect(await screen.findByText("Did not finish")).toBeTruthy();
    expect(screen.getByText("— blocked: the tariff has no rate", { exact: false })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Decision and release" }).getAttribute("href")).toBe(`#/cases/${CASE}/decision`);
    expect(screen.getByText("Waits for a person").className).toBe("status s-review");
    expect(blockersStatus(data)).toEqual({ mark: "s-failed", text: "2 holding" });
  });

  it("says nothing holds it, or that the case is closed", async () => {
    show({ status: "open", items: [] });
    expect(await screen.findByText("Nothing holds the case: its steps work by themselves.")).toBeTruthy();
    expect(blockersStatus({ status: "closed", items: [] })).toBeNull();
  });
});
