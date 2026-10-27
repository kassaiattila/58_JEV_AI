// 231 (stage D, D-c6): the product registry (jav/app/product_rules.py): the products, their condition documents and
// rules, and the tariffs, each kept as versions; a draft lists what keeps it from being made active, each problem a
// sentence the interface translates (`Said`).
import { enc, request } from "./client";
import type { OutputTemplateState } from "./outputs";
import type { Said } from "./types";

export type RegistryKind = "document" | "rule" | "product" | "tariff";

export interface Money { amount: string; currency: string }
export interface Section { clause: string; page: number | null; title: string | null }
export interface ConditionDocument {
  kind: "general" | "special" | "supplementary" | "clause"; title: string; valid_from: string; valid_to: string | null;
  sections: Section[]; references: string[];
}
export type Condition = Record<string, unknown>; // {op: value}
export interface DecisionRow { when: Record<string, Condition>; then: Record<string, unknown> }
export interface Rule {
  catalogue: string; kind: string; title: string; level: string; modules: string[]; facts: string[];
  table: { hit: "first" | "collect"; rows: DecisionRow[] };
  source: { document: string; page: number | null; clause: string | null; quote: string | null };
  applies_at: string[];
}
export interface ProductModule { code: string; name: string; kind: "base" | "extension"; requires: string[]; excludes: string[] }
export interface Product { name: string; catalogue: string; modules: ProductModule[]; documents: string[]; rules: string[]; tariff: string | null }
export interface FactorRow { when: Condition; factor: string }
export interface Factor { title: string; fact: string | null; outcome: string | null; table: FactorRow[] }
export interface TariffModule { level: string; basis: string; rate: { value: string }; minimum: Money | null; factors: string[]; only: Record<string, Condition> }
export interface Rounding { unit: string; mode: "half_up" | "half_even" | "down" }
export interface Tariff {
  title: string | null; currency: string; valid: { valid_from: string; valid_to: string | null };
  line_rounding: Rounding; total_rounding: Rounding; modules: Record<string, TariffModule>; factors: Record<string, Factor>;
  total_factors: string[]; policy_minimum: Money | null;
}

export interface RegistryVersion<C> {
  ident: string; version: number; ref: string; state: OutputTemplateState; name: string; content: C;
  made_by: string | null; made_at: string | null; activated_by: string | null; activated_at: string | null;
  retired_by: string | null; retired_at: string | null;
  /** a draft's: what keeps it from being made active now (empty: nothing) */
  problems?: Said[];
}
export interface RegistryThing<C> {
  ident: string; name: string; active: number | null; retired: boolean; versions: RegistryVersion<C>[];
  /** 231 (U0): a process's example material (the examples' machine made every version of it) */
  example?: boolean;
}

export interface CatalogueFact { type: string; level: string; title: string; unit: string | null; currency: string | null; options: string[] | null }
export interface CatalogueOutcome { type: string; title: string; combine: string; unit: string | null; currency: string | null; options: string[] | null }
export interface Catalogue { id: string; version: string; levels: string[]; facts: Record<string, CatalogueFact>; outcomes: Record<string, CatalogueOutcome>; labels: Record<string, string> }

export interface ProductRegistry {
  products: RegistryThing<Product>[]; documents: RegistryThing<ConditionDocument>[]; rules: RegistryThing<Rule>[];
  tariffs: RegistryThing<Tariff>[]; catalogues: Record<string, Catalogue>;
}

/** D-c7g: a rule proposed from a condition document, with the code's check, JEV's mark and a person's decision. */
export interface ProposalFinding { code: string; severity: "blocking" | "attention"; text: Said }
export interface ProposalNumber {
  value: string; where: "quote" | "page" | "elsewhere" | "word" | "derived" | "neutral" | "ocr" | "not_found"; page: number | null;
  kind?: "amount" | "percent" | "permille" | "count" | "decimal" | "code";
}
export interface ProposalSupport {
  mark: "supported" | "check" | "contradicted" | "not_asked"; reason: string | null; kind: string | null;
  kind_probability: number | null; rows: number[]; left_out: number | null; bands: Record<string, string>;
  model: string | null; cost_usd: number | null;
}
export interface RuleProposal {
  id: number; run_id: string; n: number; pages: number[]; title: string; kind: string; page: number; clause: string;
  rule: Rule | null; problem: Said | null; findings: ProposalFinding[]; numbers: ProposalNumber[]; support: ProposalSupport | null;
  readiness: "ready" | "confirm" | "blocked"; state: "proposed" | "accepted" | "corrected" | "rejected";
  correction: Rule | null; confirmed: string[]; reason: string | null; rule_ref: string | null; decided_by: string | null;
  decided_at: string | null; decision_state: number;
}
export interface RuleProposalRun {
  run_id: string; document_ref: string; file: string; file_sha256: string; catalogue: string; product: string | null;
  proposer: string; stand_in: boolean; verify: boolean; state: "queued" | "running" | "done" | "failed";
  limits: Record<string, string>; usage: Record<string, unknown> | null; page_count: number | null;
  skipped: Record<string, string>; ocr_pages: number[]; text_source: string | null; error: string | null;
  requested_by: string | null; requested_at: string | null; finished_at: string | null; counts: Record<string, number>;
  proposals?: RuleProposal[];
}
export interface ProposalStart {
  document: string; path: string; catalogue: string; product?: string | null; proposer: string;
  limits?: Record<string, string>; verify?: boolean;
}

export const productsApi = {
  productRegistry: () => request<ProductRegistry>("GET", "/product-registry"),
  activateRegistryVersion: (kind: RegistryKind, ident: string, version: number) =>
    request<RegistryVersion<unknown>>("POST", `/product-registry/${kind}/${enc(ident)}/versions/${version}/activate`, {}),
  retireRegistryThing: (kind: RegistryKind, ident: string) =>
    request<RegistryVersion<unknown>>("POST", `/product-registry/${kind}/${enc(ident)}/retire`, {}),
  ruleProposalRuns: () => request<{ runs: RuleProposalRun[]; stand_ins: string[] }>("GET", "/rule-proposals"),
  ruleProposalRun: (runId: string) => request<RuleProposalRun>("GET", `/rule-proposals/${enc(runId)}`),
  startRuleProposals: (body: ProposalStart) => request<RuleProposalRun>("POST", "/rule-proposals", body),
  acceptRuleProposal: (id: number, expectedState: number, confirmed: string[]) =>
    request<RuleProposal>("POST", `/rule-proposals/items/${id}/accept`, { expected_state: expectedState, confirmed }),
  correctRuleProposal: (id: number, expectedState: number, rule: unknown, confirmed: string[]) =>
    request<RuleProposal>("POST", `/rule-proposals/items/${id}/correct`, { expected_state: expectedState, rule, confirmed }),
  rejectRuleProposal: (id: number, expectedState: number, reason: string) =>
    request<RuleProposal>("POST", `/rule-proposals/items/${id}/reject`, { expected_state: expectedState, reason }),
};
