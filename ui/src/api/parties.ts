// 231 (plan stage C, C3e): the own parties - the organisations whose money the processes handle - as the shared code
// chooses from them: a package's, a case's and a workflow's party (the shared scope part `party`, `jav/app/scopes.py`;
// the register is the application's, `jav/app/parties.py`). The service serves the overview with the finance domain's
// addresses (`jav/domains/finance/api_parties.py`), whose changes and months are the finance domain's calls
// (`ui/src/domains/finance/api.ts`); until C3e all of them were in `ui/src/api/finance.ts`.
import { request } from "./client";

export interface PartyRef { id: string; name: string }
export type PartyIdentityKind = "tax" | "name" | "account";
/** A tax number, a buyer name variant or an account, with how many invoices (statements for an account) carry it. */
export interface PartyIdentity { kind: PartyIdentityKind; key: string; label: string; invoices: number }
export interface PartyAccount {
  key: string; label: string; statements: number; first: string | null; last: string | null; statement_types: string[]; currencies: string[];
  registered?: AccountDetails | null; // 138: the details a person registered (kind, bank, currencies, the days it was open)
}
/** 138: an own account or card as a person registered it; it is known even before any statement of it. */
export type AccountKind = "account" | "card";
export interface AccountDetails {
  kind: AccountKind; bank: string | null; currencies: string[]; valid_from: string | null; valid_to: string | null;
  actor?: string; updated_at?: string;
}
export interface AccountDetailsInput {
  kind: AccountKind; currencies: string[]; bank: string | null; valid_from: string | null; valid_to: string | null;
}
export interface OwnParty {
  id: string; name: string; invoices: number; first: string | null; last: string | null; statements_first: string | null;
  statements_last: string | null; accounts: PartyAccount[]; identities: PartyIdentity[]; updated_at: string;
}
/** A new party (`party_id` null) or what an existing one gains, as the data proposes it now. */
export interface PartySuggestion { id: string; party_id: string | null; name: string; invoices: number; identities: PartyIdentity[] }
export interface PartiesOverview {
  parties: OwnParty[]; suggestions: PartySuggestion[]; unassigned: PartyIdentity[]; dismissed: PartyIdentity[]; invoices: number;
  unclaimed_invoices: number; ambiguous_invoices: number; buyer_is_supplier: number; no_buyer: number; config_hash: string;
}

export const partiesApi = {
  parties: () => request<PartiesOverview>("GET", "/parties"),
};
