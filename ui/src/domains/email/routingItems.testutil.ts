// 264 (plan E, F6): the routing's documents to route are a list of the service (`routing_items`); the tests give its
// page as the service answers it, from the same synthetic attachments the element's data holds.
import { vi } from "vitest";
import { api, type DsColumn, type DsPage } from "../../api";
import type { RoutingView } from "./api";

const COLUMNS: DsColumn[] = [
  { key: "file", label: "Document", kind: "text", hidden: false, labels: null, link: "item" },
  { key: "role", label: "Role", kind: "enum", hidden: false, labels: null, group: true },
  { key: "party", label: "Party", kind: "text", hidden: false, labels: null, group: true },
  { key: "day", label: "Day", kind: "date", hidden: false, labels: null },
  { key: "proposal", label: "Proposal", kind: "text", hidden: false, labels: null },
  { key: "decision", label: "Decision", kind: "enum", hidden: false, labels: { open: "To decide", accepted: "added", rejected: "not routed" },
    badge: true, group: true },
];

/** The service's page of the routing's documents to route (the routable attachments, as `routing_items` builds them). */
export function routingPage(view: RoutingView): DsPage {
  const rows = view.items.filter((i) => i.placement.routable).map((i) => ({
    _key: i.item_id, _wp: i.package, item_id: i.item_id, file: i.file, role: i.placement.role, party: i.placement.party,
    day: i.placement.day, proposal: i.proposal?.target?.name ?? i.proposal?.new?.name ?? null,
    decision: i.decision ? i.decision.decision : "open", _item: i,
  }));
  return { dataset: { name: "routing_items", label: "Documents to route", scope: ["workpackage_id"], optional_scope: [] },
    columns: COLUMNS, rows, total: rows.length, matched: rows.length, offset: 0, limit: 100, facets: {} };
}

/** Answers the routing's list from the view; other lists answer empty. */
export function mockRouting(view: RoutingView) {
  return vi.spyOn(api, "datasetQuery").mockImplementation(async (name) => (name === "routing_items" ? routingPage(view)
    : { ...routingPage({ ...view, items: [] }), dataset: { name, label: name, scope: [], optional_scope: [] } }));
}
