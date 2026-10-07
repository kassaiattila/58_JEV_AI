import type { Reason } from "./api";

/** Public K0 contracts: identities and offsets are supplied by the saved reader. */
export interface DocumentFormat { suffix: string; label: string; flow: "document" | "native"; source_view: "pdf" | "word" | "cells" | "text" }
export type ReadingStatus = "not_attempted" | "complete" | "partial" | "unsupported" | "password_required" | "corrupt" | "resource_limited" | "temporary_error" | "excluded";
export interface ReadingIssue { stage: string; code: string; message: string; element_id: string | null }
export interface ReadingResult { occurrence_id: string; attempt_id: string; reader_key: string; status: ReadingStatus; issues: ReadingIssue[] }
export interface SourceOccurrence { occurrence_id: string; parent_id: string | null; source_version: string; original_name: string; role: string; acquisition: string; object_sha256: string | null; issues: ReadingIssue[] }
export interface TextLocator { kind: "text"; text_sha256: string; start: number; end: number }
export interface WordLocator { kind: "word"; part: string; structural_path: string; block_index: number }
export interface CellLocator { kind: "cell"; sheet: string; cell: string; row: number; column: number }
export type NativeLocator = TextLocator | WordLocator | CellLocator | { kind: "sheet"; sheet: string }
  | { kind: "image"; image_sha256: string; frame: number; host: WordLocator | CellLocator | null; region: number[] | null }
  | { kind: "pdf"; source_layer_id: string; page: number; word_ids: number[] };
export interface NativeValue { kind: "text" | "integer" | "decimal" | "boolean" | "date" | "empty" | "error"; lexical: string | null }
export interface NativeElement {
  element_id: string; parent_id: string | null; order: number; kind: "sheet" | "paragraph" | "table" | "cell" | "image" | "text" | "unsupported";
  locator: NativeLocator; availability: "read" | "empty" | "unreadable" | "unsupported"; text: string | null; hidden: boolean;
  cell: { value: NativeValue; formula: string | null; cached_value: NativeValue | null; cached_state: "not_applicable" | "missing" | "unverified"; hidden: boolean; merged_range: string | null } | null;
  occurrence_id: string; attempt_id: string; reader_key: string;
}
export interface Citation { occurrence_id: string; element_id: string; quote: string }
export interface NativeCitation extends Citation {
  locator: NativeLocator; attempt_id: string; reader_key: string; reading_id: string; publication_id: string;
  result_version: string; source_sha256: string; quote_match_count: number; quote_span: TextLocator | null;
}
export interface NativeFact {
  fact_id: string;
  proposal: { entity: string; property: string; value: string | null; unit: string | null; role: string | null; related_entity: string | null; state: string; citations: Citation[] };
  grounding: "literal_match" | "rejected" | "missing_claim"; reasons: string[]; semantic_support: number | null;
  selection_confidence: number | null; effective_value: string | null; native_citations: NativeCitation[]; confirmed: boolean;
}
/** 123: a received fact left out for breaking the presence rule; the rest of the answer was kept. */
export interface DiscardedFact { entity: string; property: string; state: string; reason: string }
export interface NativeSourcePage {
  publication_id: string; reading_id: string; result_version: string; bundle_sha256: string; source_sha256: string;
  occurrences: SourceOccurrence[]; results: ReadingResult[]; elements: NativeElement[]; texts: Record<string, string>;
  offset: number; limit: number; total: number; has_more: boolean; next_offset: number | null;
}
export interface NativeItemResult {
  run_id: string; item_id: string; kind: "document"; result_kind: "native"; result_version: string | null;
  review_version: string; result_ready: boolean;
  native_source: { reading_id: string; bundle_sha256: string; publication_id: string; source_sha256: string } | null;
  reading: { status: ReadingStatus; acquisition_status: string; attempt_ids: string[]; results: ReadingResult[] };
  interpretation_outcome: { status: "not_started" | "running" | "succeeded" | "rejected" | "failed" | "uncertain"; reason: string | null; receipt_refs: unknown[] };
  interpretation: { interpretation_id: string; payload_sha256: string; status: "completed" | "empty"; provider: string; model: string; execution: "live" | "saved_response" | "synthetic_test"; gaps: string[]; review_status: "not_reviewed"; correctness: "not_established"; discarded_facts?: DiscardedFact[] } | null;
  native_facts: NativeFact[];
  correction: { revision: number; fields: Record<string, string | null>; native_sources: Record<string, Citation[]>; confirmed: Record<string, string | null> };
  source_file: { copy?: boolean; original?: "same" | "changed" | "missing" };
  open_reasons: Reason[]; earlier_open_reasons: Reason[];
}
export interface NativeCorrectionRequest {
  kind: "native"; values: Record<string, string | null>; native_sources: Record<string, Citation[]>; confirm?: string[];
  expected_revision: number; expected_result_version: string; note?: string;
}

export const elementKey = (e: Pick<NativeElement, "occurrence_id" | "element_id">) => `${e.occurrence_id}:${e.element_id}`;
/** Python offsets count Unicode code points, not JavaScript UTF-16 units. */
export const codePointSlice = (text: string, start: number, end: number) => Array.from(text).slice(start, end).join("");
