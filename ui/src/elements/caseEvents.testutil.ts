// 263 (plan E, F3): a case's events are the one list (dataset `case_events`); the tests give the service's rows from
// the events they draw.
import { vi } from "vitest";
import { api, type CaseEvent, type DsPage } from "../api";

export function mockEvents(events: CaseEvent[]) {
  const columns = [
    { key: "at", label: "When", kind: "datetime" }, { key: "step_title", label: "Step", kind: "text" },
    { key: "kind", label: "What happened", kind: "text" }, { key: "who", label: "Who", kind: "text" },
  ];
  return vi.spyOn(api, "datasetQuery").mockImplementation(async (name) => ({
    dataset: { name, label: name, scope: ["case_id"], optional_scope: [] }, columns,
    rows: name === "case_events" ? events.map((e, i) => ({ _key: String(i), at: e.at, step_title: e.step_title, kind: e.kind, who: e.who, _detail: e.detail })) : [],
    total: events.length, matched: events.length, offset: 0, limit: 50, facets: {},
  }) as unknown as DsPage);
}
