// 181 (plan 170 L5; DECISIONS 181: a general scope): a work package's party, period and role are shown and given by
// hand (until 231 U2c a template whose steps need no party and no period made a workflow without them here). Synthetic names
// only; the local service is replaced by spies.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api, setActor, type OwnParty, type PartiesOverview, type WorkpackageView,
} from "../api";
import { setLanguage } from "../i18n";
import { ScopeForm, scopeEditable, scopeText } from "./PackageScope";

const PARTY: OwnParty = {
  id: "party-00000000000a", name: "Example Kft.", invoices: 3, first: null, last: null, statements_first: null,
  statements_last: null, accounts: [], identities: [], updated_at: "",
};
const OVERVIEW: PartiesOverview = {
  parties: [PARTY], suggestions: [], unassigned: [], dismissed: [], invoices: 0, unclaimed_invoices: 0, ambiguous_invoices: 0,
  buyer_is_supplier: 0, no_buyer: 0, config_hash: "x",
};
const ROLES = { roles: [
  { name: "incoming_invoices", title: "Incoming invoices", package_kinds: ["folder", "manual", "watch", "upload"] },
  { name: "outgoing_invoices", title: "Outgoing invoices", package_kinds: ["folder", "manual", "watch", "upload"] },
  { name: "statements", title: "Bank statements", package_kinds: ["statements"] },
] };

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function packageView(over: Partial<WorkpackageView> = {}): WorkpackageView {
  return { workpackage: { id: "wp-00000000000a", name: "June invoices", source_kind: "folder", status: "open", items: [] },
    ...over } as unknown as WorkpackageView;
}

describe("181 a package's scope", () => {
  it("is said in words, with where it comes from", () => {
    expect(scopeText({ party_id: PARTY.id, party: "Example Kft.", period_start: "2026-06-01", period_end: "2026-06-30",
      role: "incoming_invoices", role_title: "Incoming invoices", from: "workflow" }))
      .toBe("Example Kft. · 2026-06-01 – 2026-06-30 · Incoming invoices (from its workflow)");
    expect(scopeText({ party_id: null, party: null, period_start: null, period_end: null, role: "outgoing_invoices",
      role_title: "Outgoing invoices", from: "own" })).toBe("Outgoing invoices");
    expect(scopeEditable(packageView())).toBe(true);
    expect(scopeEditable(packageView({ scope: { party_id: PARTY.id, party: "Example Kft.", period_start: "2026-06-01",
      period_end: "2026-06-30", role: "statements", role_title: "Bank statements", from: "logic_pack" } }))).toBe(false);
  });

  it("is given by hand: the party, the period and a role the package's kind can hold", async () => {
    vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    vi.spyOn(api, "packageRoles").mockResolvedValue(ROLES);
    const onSave = vi.fn();
    render(<ScopeForm view={packageView()} busy={false} onSave={onSave} onClear={vi.fn()} onCancel={vi.fn()} />);
    const role = await screen.findByRole("combobox", { name: "Role" });
    await screen.findByRole("option", { name: "Outgoing invoices" });
    expect([...role.querySelectorAll("option")].map((o) => o.textContent)).toEqual(["No role", "Incoming invoices", "Outgoing invoices"]);
    fireEvent.change(await screen.findByRole("combobox", { name: "Own party" }), { target: { value: PARTY.id } });
    fireEvent.change(screen.getByLabelText("Period from"), { target: { value: "2026-06-01" } });
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true); // half a period
    fireEvent.change(screen.getByLabelText("to"), { target: { value: "2026-06-30" } });
    fireEvent.change(role, { target: { value: "incoming_invoices" } });
    fireEvent.click(save);
    expect(onSave).toHaveBeenCalledWith({ party_id: PARTY.id, period_start: "2026-06-01", period_end: "2026-06-30", role: "incoming_invoices" });
    expect(screen.queryByRole("button", { name: "Remove the package's own scope" })).toBeNull();
  });
});
