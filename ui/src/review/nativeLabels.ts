import { t } from "../i18n";
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

/** 120: reading issues as everyday sentences, one line per kind with its count; the raw messages stay in the
 *  technical details. */
const ISSUE: Record<string, string> = tmap({
  download_missing: "A file or attachment was not received",
  download_truncated: "A file was received incomplete",
  inventory_unknown: "The list of files could not be fully established",
  unsupported: "Part of the file has an unsupported format",
  password_required: "The file is password-protected",
  corrupt: "The file is damaged",
  resource_limit: "The file exceeds a reading limit",
  temporary_error: "A temporary reading error occurred",
  excluded: "Part of the file was left out for safety",
  needs_ocr: "Images or scanned parts were not read as text",
  formula_cache_missing: "A formula has no saved result",
  unread_content: "Some content is kept only in the original, for example display formatting or an embedded object",
  protection_unavailable: "Text recognition ran without full isolation; check the recognised text",
});
export function issueSummary(issues: { code: string }[]): string[] {
  const counts = new Map<string, number>();
  for (const issue of issues) counts.set(issue.code, (counts.get(issue.code) ?? 0) + 1);
  return [...counts].map(([code, n]) => {
    const text = ISSUE[code] ?? code;
    return n > 1 ? t("{{text}} ({{n}} places)", { text, n }) : text;
  });
}

/** 120: the service's interpretation outcome reason in the display language (an error class stays as it is). */
export function outcomeReasonText(reason: string): string {
  const stopped = /^Interpretation stopped: (\w+)$/.exec(reason);
  return stopped ? t("Interpretation stopped ({{error}})", { error: stopped[1] }) : t(reason);
}

