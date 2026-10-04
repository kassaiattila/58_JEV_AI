import { tmap } from "../labels";

const STATE: Record<string, string> = tmap({
  not_attempted: "Not attempted", complete: "Complete", partial: "Partial", unsupported: "Unsupported",
  password_required: "Password required", corrupt: "Corrupt source", resource_limited: "Resource limit reached",
  temporary_error: "Temporary error", excluded: "Excluded", unknown: "Unknown", not_started: "Not started",
  running: "Running", succeeded: "Succeeded", rejected: "Rejected", failed: "Failed", uncertain: "Uncertain",
  stated: "Stated", missing: "Missing", conflicting: "Conflicting", literal_match: "Literal match",
  missing_claim: "Missing claim", read: "Read", empty: "Empty", unreadable: "Unreadable",
  sheet: "Sheet", paragraph: "Paragraph", table: "Table", cell: "Cell", image: "Image", text: "Text",
  integer: "Integer", decimal: "Decimal", boolean: "Boolean", date: "Date", error: "Error",
});

/** Translate service metadata enums, never document content or extracted values. */
export const nativeStateLabel = (state: string): string => STATE[state] ?? state;
