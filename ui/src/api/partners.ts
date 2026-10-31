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
/** 231 (U3e): an own party as the partner list shows it, with the role "own"; it is edited in the own parties' register */
export interface OwnPartnerRow { party_id: string; name: string; tax_number: string | null; changed_at: string | null }
export const OWN_ROLE = "own";
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
    request<{ partners: PartnerRow[]; roles: PartnerRoles; own: OwnPartnerRow[] }>("GET", `/partners${query(q)}`),
  partner: (id: string) => request<Partner>("GET", `/partners/${enc(id)}`),
  createPartner: (values: PartnerValues) => request<Partner>("POST", "/partners", values),
  updatePartner: (id: string, values: PartnerValues, expectedVersion: number) =>
    request<Partner>("PUT", `/partners/${enc(id)}`, { ...values, expected_version: expectedVersion }),
  retirePartner: (id: string) => request<Partner>("POST", `/partners/${enc(id)}/retire`, {}),
  restorePartner: (id: string) => request<Partner>("POST", `/partners/${enc(id)}/restore`, {}),
  partnerSuggestions: () => request<{ suggestions: PartnerSuggestion[] }>("GET", "/partners/suggestions"),
  /** 264 (G1): proposals recorded at once with their suggested values - the named ones (`null`: all shown now) */
  acceptPartnerSuggestions: (keys: string[] | null, names: Record<string, string> = {}) =>
    request<{ created: string[]; skipped: number }>("POST", "/partners/suggestions/accept", keys ? { keys, names } : { all: true, names }),
  dismissPartnerSuggestions: (keys: string[]) => request<{ dismissed: string[] }>("POST", "/partners/suggestions/dismiss", { keys }),
  restorePartnerSuggestions: (keys: string[]) => request<{ restored: string[] }>("POST", "/partners/suggestions/restore", { keys }),
};
