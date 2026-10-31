// 140 (backlog F-package-kinds K3): the create form asked the goal first, then the source (231 C3b3: the bank
// statements' process pack's general form; C3b5a: the statement package's own form went, with its survey's tests; U2c:
// the wizard went, a process is chosen on New case); the package's page shows each item's statement. Synthetic names and made-up accounts only; the local service is replaced by spies. Expectations use the
// English interface; a separate check makes sure every new label has a Hungarian translation.
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type OwnParty } from "../../api";
import type { PartyMonths } from "./api";
import hungarian from "../../i18n/hu-native.json";
import { setLanguage, t } from "../../i18n";
import { reasonText } from "../../labels";
import { StatementPackagePanel } from "./StatementPackagePanel";

const PARTY: OwnParty = {
  id: "party-00000000000a", name: "Example Kft.", invoices: 0, first: null, last: null, statements_first: null,
  statements_last: null, accounts: [], identities: [], updated_at: "",
};
const MONTHS: PartyMonths = {
  party: { id: PARTY.id, name: PARTY.name }, start: "2026-01", end: "2026-09", months: [], today: "2026-10-10", columns: [],
  invoices: [], summary: { ok: 0, unapproved: 0, unverified: 0, partial: 0, missing: 0, overlap: 0, break: 0 },
};
beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

describe("the package's page and its to-dos", () => {
  it("shows each item's statement state and the party's months", async () => {
    vi.spyOn(api, "partyMonths").mockResolvedValue(MONTHS);
    // 264 (F6): the statements are the one list of the service; a conflicting one leads to its review page
    const query = vi.spyOn(api, "datasetQuery").mockResolvedValue({ dataset: { name: "statement_package_statements", label: "",
      scope: ["workpackage_id"], optional_scope: [] }, columns: [
      { key: "file", label: "File", kind: "text", hidden: false, labels: null, link: "item" },
      { key: "state", label: "State", kind: "enum", hidden: false, labels: { pending: "no statement from it yet", conflict: "x" }, badge: true },
    ], rows: [{ _key: "2", _wp: "wp-1", file: "other-bank.pdf", state: "pending" }, { _key: "3", _wp: "wp-1", file: "april.json", state: "conflict" }],
      total: 2, matched: 2, offset: 0, limit: 100, facets: {} });
    render(<StatementPackagePanel view={{
      scope: { workpackage_id: "wp-1", party_id: PARTY.id, party: { id: PARTY.id, name: PARTY.name }, period_start: "2026-01-01",
        period_end: "2026-09-30", revision: 1 },
      statements: [
        { item_id: "1", kind: "statement_table", file: "may.json", state: "valid", account: "…6666", currency: "HUF",
          period_start: "2026-05-01", period_end: "2026-05-31", rank: "code_checked" },
        { item_id: "2", kind: "document", file: "other-bank.pdf", state: "pending" },
      ],
    }} />);
    expect(screen.getByText("1 valid, 0 replaced, 0 to choose, 1 without a statement yet")).toBeTruthy();
    expect(await screen.findByText("no statement from it yet")).toBeTruthy();
    expect(query.mock.calls[0].slice(0, 2)).toEqual(["statement_package_statements", { workpackage_id: "wp-1" }]);
    expect(screen.getByRole("link", { name: "Choose the valid one →" }).getAttribute("href")).toBe("#/workpackages/wp-1/review/3");
    await screen.findByText("The party has no account or card yet: its first statements will bring them.");
  });

  it("names the statement package's to-dos in plain words", () => {
    expect(reasonText("statements:not_a_statement:invoice_hu")).toMatch(/^This PDF is not a bank statement/);
    expect(reasonText("statements:other_party:party-00000000000b")).toMatch(/another own party/);
  });

  it("has a Hungarian translation for every new label", () => {
    const labels = ["What is the package for?", "Bank statements", "Survey the files", "Statements of the package",
      "goes to {{party}}", "replaces {{n}} statement(s)", "no statement from it yet"];
    for (const label of labels) expect((hungarian as Record<string, string>)[label], label).toBeTruthy();
    expect(t("Bank statements")).toBe("Bank statements");
  });
});
