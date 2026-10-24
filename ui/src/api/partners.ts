// 231 (plan stage B, B1; DECISIONS 231): the shared partner register (jav/app/partners.py): the outside parties every
// process deals with, each with the roles it plays, every change a version of its own; the domains' proposals.
import { enc, request } from "./client";

export interface PartnerValues {
  name: string; tax_number: string | null; email: string | null; phone: string | null; address: string | null;
  note: string | null; roles: string[];
}
export interface PartnerRow extends PartnerValues { partner_id: string; version: number; retired: boolean; changed_at: string | null }
export interface PartnerVersion extends PartnerValues {
  version: number; state: "draft" | "active" | "superseded" | "retired"; made_by: string; made_at: string;
  activated_at: string | null; retired_by: string | null; retired_at: string | null;
}
export interface Partner extends PartnerValues { partner_id: string; version: number; retired: boolean; versions: PartnerVersion[] }
export type PartnerRoles = Record<string, { label: string; what: string }>;
export interface PartnerSuggestion { name: string; tax_number: string | null; roles: string[]; seen: number; sources: string[]; last: string | null }

const query = (q: { q?: string; role?: string; retired?: boolean }) => {
  const s = new URLSearchParams();
  if (q.q) s.set("q", q.q);
  if (q.role) s.set("role", q.role);
  if (q.retired) s.set("retired", "true");
  return s.toString() ? `?${s}` : "";
};

export const partnersApi = {
  partners: (q: { q?: string; role?: string; retired?: boolean } = {}) =>
    request<{ partners: PartnerRow[]; roles: PartnerRoles }>("GET", `/partners${query(q)}`),
  partner: (id: string) => request<Partner>("GET", `/partners/${enc(id)}`),
  createPartner: (values: PartnerValues) => request<Partner>("POST", "/partners", values),
  updatePartner: (id: string, values: PartnerValues, expectedVersion: number) =>
    request<Partner>("PUT", `/partners/${enc(id)}`, { ...values, expected_version: expectedVersion }),
  retirePartner: (id: string) => request<Partner>("POST", `/partners/${enc(id)}/retire`, {}),
  restorePartner: (id: string) => request<Partner>("POST", `/partners/${enc(id)}/restore`, {}),
  partnerSuggestions: () => request<{ suggestions: PartnerSuggestion[] }>("GET", "/partners/suggestions"),
};
