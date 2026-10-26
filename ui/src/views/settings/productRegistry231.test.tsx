// 231 (stage D, D-c6): the product registry in Settings. The products list opens a product with its cover modules, its
// condition documents, its rules (each a decision table with the clause it was read from) and its tariff; a draft shows
// what keeps it from being made active, in the interface's language, and its maker cannot make it active: another
// person can, with one solid button. The tariffs read as the order the premium is computed in. Invented data, a mocked
// service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setActor, type Catalogue, type ProductRegistry, type RegistryThing, type Rule } from "../../api";
import { setLanguage } from "../../i18n";
import { ProductsPanel } from "./ProductsPanel";
import { TariffsPanel } from "./TariffsPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic approver"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const AT = "2026-10-26T09:00:00+00:00";
const HUF = (amount: string) => ({ amount, currency: "HUF" });
const CAT: Catalogue = {
  id: "property", version: "1.2.0", levels: ["holder", "site", "asset_group"],
  facts: {
    asset_group: { type: "code", level: "asset_group", title: "Asset group", unit: null, currency: null, options: ["stock", "cash"] },
    sum_insured: { type: "money", level: "asset_group", title: "Sum insured", unit: null, currency: "HUF", options: null },
    activity_code: { type: "code", level: "holder", title: "Activity code (NACE)", unit: null, currency: null, options: null },
    protection_class_in_place: { type: "count", level: "site", title: "Protection class in place", unit: null, currency: null, options: null },
  },
  outcomes: {
    protection_class_required: { type: "count", title: "Protection class required", combine: "max", unit: null, currency: null, options: null },
    measures: { type: "codes", title: "Security measures required", combine: "union", unit: null, currency: null, options: null },
    premium_factor: { type: "decimal", title: "Premium factor", combine: "one", unit: null, currency: null, options: null },
  },
  labels: { asset_group: "Asset group", cash: "Cash", stock: "Stock", safe_grade_1: "A safe of grade 1 at least" },
};
const CASH_RULE: Rule = {
  catalogue: "property", kind: "requirement", title: "Protection class of cash", level: "asset_group", modules: ["burglary"],
  facts: ["asset_group", "sum_insured"], applies_at: ["quote"],
  table: { hit: "first", rows: [
    { when: { asset_group: { eq: "cash" }, sum_insured: { gt: HUF("1000000") } }, then: { protection_class_required: 3, measures: ["safe_grade_1"] } },
    { when: { asset_group: { eq: "cash" } }, then: { protection_class_required: 2 } },
  ] },
  source: { document: "invented_security@1", page: 1, clause: "1", quote: "Cash up to 1 000 000 needs protection class 2" },
};
const version = <C,>(ident: string, n: number, state: "draft" | "active", content: C, extra: object = {}) => ({
  ident, version: n, ref: `${ident}@${n}`, state, name: (content as { name?: string; title?: string }).name ?? (content as { title?: string }).title ?? "",
  content, made_by: "Synthetic maker", made_at: AT, activated_by: state === "active" ? "Synthetic approver" : null,
  activated_at: state === "active" ? AT : null, retired_by: null, retired_at: null, ...extra,
});
const thing = <C,>(ident: string, versions: ReturnType<typeof version<C>>[]): RegistryThing<C> => ({
  ident, name: versions[0].name, active: versions.find((v) => v.state === "active")?.version ?? null, retired: false, versions,
});
const PRODUCT = { name: "Invented business property", catalogue: "property", documents: ["invented_security@1"], rules: ["cash_class@1"],
  tariff: "invented_tariff", modules: [
    { code: "property", name: "Property", kind: "base" as const, requires: [], excludes: [] },
    { code: "burglary", name: "Burglary", kind: "extension" as const, requires: ["property"], excludes: [] }] };
const TARIFF = {
  title: "Invented tariff", currency: "HUF", valid: { valid_from: "2026-01-01", valid_to: "2027-12-31" },
  line_rounding: { unit: "1", mode: "half_up" as const }, total_rounding: { unit: "100", mode: "half_up" as const },
  modules: { burglary: { level: "asset_group", basis: "sum_insured", rate: { value: "1.8" }, minimum: HUF("15000"), factors: ["protection"],
    only: { asset_group: { in: ["stock", "cash"] } } } },
  factors: { protection: { title: "Protection in place", fact: "protection_class_in_place", outcome: null,
    table: [{ when: { gte: 3 }, factor: "0.9" }, { when: {}, factor: "1.0" }] } },
  total_factors: [], policy_minimum: HUF("25000"),
};
const REGISTRY = (problems: { text: string; template?: string; params?: Record<string, string>; within?: object | null }[]): ProductRegistry => ({
  products: [thing("invented_property", [version("invented_property", 1, "draft", PRODUCT, { problems })])],
  documents: [thing("invented_security", [version("invented_security", 1, "active", {
    kind: "supplementary" as const, title: "Invented security rules (KB-VV-2026)", valid_from: "2026-01-01", valid_to: null, references: [],
    sections: [{ clause: "1", page: 1, title: "Cash" }] })])],
  rules: [thing("cash_class", [version("cash_class", 1, "active", CASH_RULE)])],
  tariffs: [thing("invented_tariff", [version("invented_tariff", 1, "active", TARIFF)])],
  catalogues: { property: CAT },
});
const DRAFT_RULE = { text: "rule cash_class@1: still a draft", template: "still a draft", params: {},
  within: { text: "rule cash_class@1", template: "rule {{ref}}", params: { ref: "cash_class@1" }, within: null } };

describe("the product registry in Settings (231 D-c6)", () => {
  it("opens a product with its modules, documents, rules and tariff, and a rule's decision table with its clause", async () => {
    vi.spyOn(api, "productRegistry").mockResolvedValue(REGISTRY([]));
    render(<ProductsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Invented business property" }));
    const card = await screen.findByRole("region", { name: "Invented business property" });
    expect(within(within(card).getByRole("table", { name: "Cover modules" })).getByText("Extension")).toBeTruthy();
    expect(within(card).getByRole("table", { name: "Condition documents" }).textContent).toContain("Invented security rules (KB-VV-2026)");
    const rules = within(card).getByRole("table", { name: "Rules" });
    expect(within(rules).getByText("KB-VV-2026 · clause 1 · p. 1")).toBeTruthy();
    fireEvent.click(within(rules).getByRole("button", { name: "Protection class of cash" }));
    const table = within(card).getByRole("table", { name: "Decision table" });
    const [head, first] = within(table).getAllByRole("row");
    expect(head.textContent).toBe("#Asset groupSum insuredProtection class requiredSecurity measures required");
    expect(first.textContent).toBe("1= Cash> 1,000,000 HUF3A safe of grade 1 at least");
    expect(within(card).getByText("„Cash up to 1 000 000 needs protection class 2”")).toBeTruthy();
    expect(within(card).getByText("Invented tariff")).toBeTruthy();
  });

  it("shows a draft's problems in the interface's language and keeps it from being made active", async () => {
    vi.spyOn(api, "productRegistry").mockResolvedValue(REGISTRY([DRAFT_RULE]));
    await setLanguage("hu");
    render(<ProductsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Invented business property" }));
    const blockers = await screen.findByRole("list", { name: "Ami akadályozza az élesítést" });
    expect(blockers.textContent).toBe("cash_class@1 szabály: még vázlat");
    const make = screen.getByRole("button", { name: "A(z) 1. változat élesítése" }) as HTMLButtonElement;
    expect(make.disabled).toBe(true);
    expect(make.className).toBe("secondary");
  });

  it("lets another person than the maker make a draft active with the one solid button, and not its maker", async () => {
    vi.spyOn(api, "productRegistry").mockResolvedValue(REGISTRY([]));
    const activate = vi.spyOn(api, "activateRegistryVersion").mockResolvedValue({} as never);
    render(<ProductsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Invented business property" }));
    const make = await screen.findByRole("button", { name: "Make version 1 active" }) as HTMLButtonElement;
    expect(make.className).toBe("primary");
    fireEvent.click(make);
    fireEvent.click(await screen.findByRole("button", { name: "Sure? Click again" }));
    await waitFor(() => expect(activate).toHaveBeenCalledWith("product", "invented_property", 1));
    cleanup();
    setActor("Synthetic maker");
    render(<ProductsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Invented business property" }));
    expect((await screen.findByRole("button", { name: "Make version 1 active" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("You made this version: another person makes it active.")).toBeTruthy();
  });

  it("lists a refused activation's problems", async () => {
    vi.spyOn(api, "productRegistry").mockResolvedValue(REGISTRY([]));
    vi.spyOn(api, "activateRegistryVersion").mockRejectedValue(
      new ApiError(422, "manifest_refused", "the product cannot be made active", [], { problems: [DRAFT_RULE] }));
    render(<ProductsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Invented business property" }));
    fireEvent.click(await screen.findByRole("button", { name: "Make version 1 active" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sure? Click again" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("It was not made active:rule cash_class@1: still a draft");
  });

  it("reads a tariff as the order its premium is computed in", async () => {
    vi.spyOn(api, "productRegistry").mockResolvedValue(REGISTRY([]));
    render(<TariffsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Invented tariff" }));
    const card = await screen.findByRole("region", { name: "Invented tariff" });
    const modules = within(card).getByRole("table", { name: "Cover modules" });
    expect(within(modules).getAllByRole("row")[1].textContent).toBe("BurglaryAsset groupSum insured1.8 ‰Asset group one of Stock, CashProtection in place15,000 HUF");
    const factor = within(card).getByRole("table", { name: "Protection in place" });
    expect(within(factor).getAllByRole("row").map((r) => r.textContent)).toEqual(["WhenFactor", "≥ 3× 0.9", "any× 1"]);
    expect(card.textContent).toContain("The total rounded to 100 HUF, half up; below the policy minimum of 25,000 HUF, the minimum.");
  });
});
