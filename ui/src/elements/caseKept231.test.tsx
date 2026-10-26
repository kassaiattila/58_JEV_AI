// 231 (stage D0, D0-e; the owner's decision of 2026-10-26): a case runs to its end with the versions it started with,
// and its history says which at its start: the price list's and the template's version, and the rule files'. A case
// started before keeps nothing, and its start says nothing more. Synthetic data.
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { CaseEvent, CaseView } from "../api";
import { setLanguage } from "../i18n";
import { elementOf } from "./registry";

beforeEach(async () => { await setLanguage("en"); });

const page = { case: { id: "wp-0000000d0e00", pack: "invented", version: "1.0.0", title: "Invented", name: "Invented case",
  status: "open" }, steps: {}, tabs: [], next: null } as unknown as CaseView;

function history(events: CaseEvent[]) {
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

  it("are not named for a case started before it kept them", async () => {
    history([started({})]);
    expect(await screen.findByText("The case started")).toBeTruthy();
    expect(screen.queryByText(/^It keeps from its start/)).toBe(null);
  });
});
