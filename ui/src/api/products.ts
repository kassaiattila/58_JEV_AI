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
export interface RegistryThing<C> { ident: string; name: string; active: number | null; retired: boolean; versions: RegistryVersion<C>[] }

export interface CatalogueFact { type: string; level: string; title: string; unit: string | null; currency: string | null; options: string[] | null }
export interface CatalogueOutcome { type: string; title: string; combine: string; unit: string | null; currency: string | null; options: string[] | null }
export interface Catalogue { id: string; version: string; levels: string[]; facts: Record<string, CatalogueFact>; outcomes: Record<string, CatalogueOutcome>; labels: Record<string, string> }

export interface ProductRegistry {
  products: RegistryThing<Product>[]; documents: RegistryThing<ConditionDocument>[]; rules: RegistryThing<Rule>[];
  tariffs: RegistryThing<Tariff>[]; catalogues: Record<string, Catalogue>;
}

export const productsApi = {
  productRegistry: () => request<ProductRegistry>("GET", "/product-registry"),
  activateRegistryVersion: (kind: RegistryKind, ident: string, version: number) =>
    request<RegistryVersion<unknown>>("POST", `/product-registry/${kind}/${enc(ident)}/versions/${version}/activate`, {}),
  retireRegistryThing: (kind: RegistryKind, ident: string) =>
    request<RegistryVersion<unknown>>("POST", `/product-registry/${kind}/${enc(ident)}/retire`, {}),
};
