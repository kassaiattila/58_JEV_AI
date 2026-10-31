// 231 (stage D0, D0-e; the owner's decision of 2026-10-26): a case runs to its end with the versions it started with,
// and its history says which at its start: the price list's and the template's version, and the rule files'. A case
// started before keeps nothing, and its start says nothing more. Synthetic data.
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CaseEvent, CaseView } from "../api";
import { setLanguage } from "../i18n";
import hungarian from "../i18n/hu-native.json";
import { elementOf } from "./registry";
import { mockEvents } from "./caseEvents.testutil";

beforeEach(async () => { await setLanguage("en"); });
afterEach(() => vi.restoreAllMocks());

const page = { case: { id: "wp-0000000d0e00", pack: "invented", version: "1.0.0", title: "Invented", name: "Invented case",
  status: "open" }, steps: {}, tabs: [], next: null } as unknown as CaseView;

function history(events: CaseEvent[]) {
  mockEvents(events);  // 263 (F3): the events are the service's list
  render(<>{elementOf("timeline")!.render({ caseId: page.case.id, element: { type: "timeline", step: null, data: { events } },
    page, onChanged: () => {} })}</>);
}

const started = (detail: CaseEvent["detail"]): CaseEvent =>
  ({ at: "2026-10-26T09:00:00+00:00", kind: "started", step: null, step_title: null, who: "Synthetic owner", detail });

describe("the versions a case keeps from its start", () => {
  it("are named on its start", async () => {
    history([started({ kept: {
      resources: [{ key: "price_list", label: "Price list", name: "Invented 2026", version: 3 },
                  { key: "template:quote", label: "Output template", name: "The built-in template", version: null }],
      rules: [{ file: "quotes", version: "1.2.0" }, { file: "price_lists", version: "1.1.0" }] } })]);
    expect((await screen.findByText(/^It keeps from its start/)).textContent).toBe(
      "It keeps from its start: Price list: Invented 2026, version 3 · Output template: The built-in template"
      + " · rule files: quotes 1.2.0, price_lists 1.1.0");
  });

  it("D0-z: the process core's own note is in the interface's language, a person's as written", async () => {
    await setLanguage("hu");
    history([{ ...started({}), kind: "task_withdrawn", detail: { task_kind: "step_start", note: "the step moved on" } },
             { ...started({}), kind: "reopened", detail: { note: "A new price list is needed" } }]);
    expect(await screen.findByText(hungarian["the step moved on"])).toBeTruthy();
    expect(screen.queryByText("the step moved on")).toBe(null);
    expect(screen.getByText("A new price list is needed")).toBeTruthy();
  });

  it("are not named for a case started before it kept them", async () => {
    history([started({})]);
    expect(await screen.findByText("The case started")).toBeTruthy();
    expect(screen.queryByText(/^It keeps from its start/)).toBe(null);
  });

  it("263 (F4): are not named when its process uses nothing that keeps a version (no line ending in a colon)", async () => {
    history([started({ kept: { resources: [], rules: [] } })]);
    expect(await screen.findByText("The case started")).toBeTruthy();
    expect(screen.queryByText(/^It keeps from its start/)).toBe(null);
  });
});
